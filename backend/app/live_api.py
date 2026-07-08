"""신규 라이브 API 라우터 — 뉴스 / 실시간 상세 / 외국인 관광객 밀집 지역.

- GET /api/news         : 구글 뉴스 RSS '제주' 검색 상위 4건 (30분 캐시)
- GET /api/live/detail  : 카테고리별(fuel/weather/traffic) 실시간 상세 (5분 캐시, refresh=1 무시)
- GET /api/live/density : 읍면동 단위 외국인 단기체류 유동인구 상위 12곳 (30분 캐시)

main.py 의 인메모리 TTL 캐시 패턴을 따르되, 순환 import 를 피하기 위해
모듈 자체 캐시를 둔다. 외부 HTTP 호출은 tools.jeju_live 의 _get 을 재사용한다.
"""
import asyncio
import datetime
import logging
import time
import xml.etree.ElementTree as ET

import httpx
from fastapi import APIRouter, Query

from app.config import settings
from app.connectors._extract import load_sources
from app.tools.jeju_live import (
    JejuFuelTool,
    JejuGasStationTool,
    JejuTrafficTool,
    JejuWeatherTool,
    _get,
)

logger = logging.getLogger("jeju-genie.live_api")

router = APIRouter()

# ── 인메모리 TTL 캐시 (main.py 와 동일 패턴) ─────────────────
_cache: dict[str, tuple[float, object]] = {}


def _cache_get(key: str, ttl: float):
    ent = _cache.get(key)
    if ent is not None and time.monotonic() - ent[0] < ttl:
        return ent[1]
    return None


def _cache_set(key: str, value):
    _cache[key] = (time.monotonic(), value)


# ── 1. 오늘의 제주 뉴스 ──────────────────────────────────────

# 주의: _get 은 params 인자가 URL 쿼리를 대체하므로 쿼리는 반드시 params 로 넘긴다.
_NEWS_RSS_URL = "https://news.google.com/rss/search"
_NEWS_RSS_PARAMS = {"q": "제주", "hl": "ko", "gl": "KR", "ceid": "KR:ko"}


@router.get("/api/news")
async def news():
    """구글 뉴스 RSS '제주' 검색 상위 4건 (30분 캐시). 실패 시 빈 목록."""
    cached = _cache_get("news", 1800)
    if cached is not None:
        return cached
    try:
        r = await _get(_NEWS_RSS_URL, _NEWS_RSS_PARAMS)
        root = ET.fromstring(r.content)
    except (httpx.HTTPError, ET.ParseError):
        logger.exception("/api/news RSS 조회 실패")
        return {"items": []}
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        source = (item.findtext("source") or "").strip()
        if not title or not url:
            continue
        # 구글 뉴스 제목은 끝에 " - 언론사"가 붙으므로 source 와 중복되면 잘라낸다.
        suffix = f" - {source}"
        if source and title.endswith(suffix):
            title = title[: -len(suffix)].rstrip()
        items.append({"title": title, "url": url, "source": source})
        if len(items) >= 4:
            break
    result = {"items": items}
    if items:  # 빈 결과는 캐시하지 않고 다음 요청에서 재시도
        _cache_set("news", result)
    return result


# ── 2. 실시간 상세 (카테고리별) ──────────────────────────────

# 카테고리 → 도구 클래스 목록. fuel 은 도 평균 유가 + 최저가 주유소 둘 다 조회.
_DETAIL_TOOLS: dict[str, tuple] = {
    "fuel": (JejuFuelTool, JejuGasStationTool),
    "weather": (JejuWeatherTool,),
    "traffic": (JejuTrafficTool,),
}


@router.get("/api/live/detail")
async def live_detail(
    category: str = Query(..., pattern="^(fuel|weather|traffic)$"),
    refresh: int = 0,
):
    """카테고리별 실시간 상세 (5분 캐시, refresh=1 이면 캐시 무시)."""
    key = f"live_detail:{category}"
    if not refresh:
        cached = _cache_get(key, 300)
        if cached is not None:
            return cached
    tools = [cls() for cls in _DETAIL_TOOLS[category]]
    tools = [t for t in tools if t.enabled()]
    results = await asyncio.gather(*(t.run() for t in tools), return_exceptions=True)
    items = []
    for tool, res in zip(tools, results):
        # 예외/빈 결과/도구의 실패 문구는 제외한다 (main.live_summary 와 동일 기준).
        if isinstance(res, BaseException) or not res or "조회 실패" in res:
            continue
        items.append({"label": tool.label or tool.name, "text": res})
    result = {"category": category, "items": items}
    if items:  # 전부 실패한 응답은 캐시하지 않는다
        _cache_set(key, result)
    return result


# ── 3. 외국인 관광객 밀집 지역 ───────────────────────────────

# 사용 데이터셋: 제주데이터허브 '읍면동 단위 외국인 단기체류 유동인구'.
# 실측 확인 사항:
# - startDate/endDate=YYYYMM 필수, nationality=중국 필터 동작 (월별 읍면동당 1행)
# - number/page 는 필터와 섞으면 페이지가 넘어가지 않음(항상 같은 10행)
# - limit 파라미터는 정상 동작 (최대 100) → 한 번에 전체 43개 읍면동 수신
# - 데이터는 약 2~3개월 지연 게시 (2026-07 현재 최신 2026-04)
_DENSITY_DATASET = "읍면동 단위 외국인 단기체류 유동인구"

# 제주 읍면동 대표 좌표 (WGS84 근사 중심점). 데이터의 실제 emd 명칭 43곳 전체.
_EMD_COORDS: dict[str, tuple[float, float]] = {
    # 제주시 동지역
    "일도1동": (33.5139, 126.5264),
    "일도2동": (33.5083, 126.5397),
    "이도1동": (33.5064, 126.5253),
    "이도2동": (33.4996, 126.5325),
    "삼도1동": (33.5087, 126.5175),
    "삼도2동": (33.5127, 126.5194),
    "용담1동": (33.5117, 126.5148),
    "용담2동": (33.5093, 126.4906),
    "건입동": (33.5175, 126.5321),
    "화북동": (33.5202, 126.5700),
    "삼양동": (33.5250, 126.5860),
    "봉개동": (33.4870, 126.6070),
    "아라동": (33.4740, 126.5470),
    "오라동": (33.4900, 126.5140),
    "연동": (33.4890, 126.4930),
    "노형동": (33.4820, 126.4790),
    "외도동": (33.4880, 126.4330),
    "이호동": (33.4975, 126.4550),
    "도두동": (33.5060, 126.4680),
    # 제주시 읍면
    "한림읍": (33.4110, 126.2690),
    "애월읍": (33.4630, 126.3310),
    "구좌읍": (33.5230, 126.8580),
    "조천읍": (33.5380, 126.6350),
    "한경면": (33.3450, 126.1960),
    "추자면": (33.9610, 126.3000),
    "우도면": (33.5060, 126.9530),
    # 서귀포시 동지역
    "송산동": (33.2440, 126.5760),
    "정방동": (33.2470, 126.5680),
    "중앙동": (33.2490, 126.5630),
    "천지동": (33.2450, 126.5580),
    "효돈동": (33.2600, 126.6120),
    "영천동": (33.2700, 126.5920),
    "동홍동": (33.2610, 126.5670),
    "서홍동": (33.2590, 126.5480),
    "대륜동": (33.2440, 126.5100),
    "대천동": (33.2500, 126.4860),
    "중문동": (33.2540, 126.4360),
    "예래동": (33.2470, 126.3920),
    # 서귀포시 읍면
    "대정읍": (33.2270, 126.2510),
    "남원읍": (33.2800, 126.7180),
    "성산읍": (33.4370, 126.9160),
    "안덕면": (33.2570, 126.3490),
    "표선면": (33.3270, 126.8320),
}

_DENSITY_TOP_N = 12  # 지도에 표시할 상위 지역 수
_DENSITY_LOOKBACK = 8  # 최신 데이터를 찾아 거슬러 올라갈 최대 개월 수


def _recent_months(n: int = _DENSITY_LOOKBACK) -> list[str]:
    """지난달부터 거꾸로 n개월의 YYYYMM 목록 (월간 데이터는 지연 게시되므로)."""
    first = datetime.date.today().replace(day=1)
    months = []
    for _ in range(n):
        first = (first - datetime.timedelta(days=1)).replace(day=1)
        months.append(first.strftime("%Y%m"))
    return months


@router.get("/api/live/density")
async def live_density():
    """외국인 관광객 밀집 지역 상위 12곳 — 읍면동 유동인구 기준 (30분 캐시)."""
    cached = _cache_get("density", 1800)
    if cached is not None:
        return cached
    empty = {"asof": None, "points": []}
    if not settings.jejudatahub_project_key:
        return empty
    dataset = next(
        (d for d in load_sources().get("jejudatahub", [])
         if d.get("name") == _DENSITY_DATASET),
        None,
    )
    if not dataset:
        return empty
    url = (f"https://open.jejudatahub.net/api/proxy/"
           f"{dataset['apicode']}/{settings.jejudatahub_project_key}")

    rows, asof_month = [], None
    for month in _recent_months():
        try:
            r = await _get(url, {"startDate": month, "endDate": month,
                                 "nationality": "중국", "limit": 100})
            rows = r.json().get("data", [])
        except (httpx.HTTPError, ValueError):
            logger.exception("/api/live/density 데이터허브 조회 실패 (%s)", month)
            return empty
        if rows:
            asof_month = month
            break
    if not rows:
        return empty

    # 읍면동별 유동인구 집계 (월간 데이터라 보통 1행이지만 방어적으로 합산)
    agg: dict[str, int] = {}
    for row in rows:
        emd = (row.get("emd") or "").strip()
        pop = row.get("visitPop")
        if emd and isinstance(pop, (int, float)):
            agg[emd] = agg.get(emd, 0) + int(pop)

    # 좌표 매핑되는 지역만 남기고 상위 N곳 선정
    ranked = sorted(
        ((emd, val) for emd, val in agg.items() if emd in _EMD_COORDS),
        key=lambda x: -x[1],
    )[:_DENSITY_TOP_N]
    if not ranked:
        return empty

    # level: 선정된 지역을 값 순위 기준 3등분 — 상위 1/3=1(빨강), 중위=2(주황), 하위=3(노랑)
    n = len(ranked)
    points = []
    for i, (emd, val) in enumerate(ranked):
        lat, lng = _EMD_COORDS[emd]
        points.append({
            "name": emd, "lat": lat, "lng": lng,
            "value": val, "level": min(3, i * 3 // n + 1),
        })
    result = {"asof": f"{asof_month[:4]}-{asof_month[4:]} 기준", "points": points}
    _cache_set("density", result)
    return result
