# -*- coding: utf-8 -*-
"""신규 라이브 API(app/live_api.py) 단위 테스트.

네트워크는 live_api._get 을 가짜 async 함수로 갈아끼워 차단한다.
엔드포인트 함수를 asyncio.run 으로 직접 호출한다 (TestClient 불필요).
"""
import asyncio
import json

import httpx
import pytest

import app.live_api as api


class FakeResponse:
    """httpx.Response 대역 — text/content/json()만 흉내낸다."""

    def __init__(self, text: str = "", json_data=None):
        if json_data is not None and not text:
            text = json.dumps(json_data, ensure_ascii=False)
        self.text = text
        self.content = text.encode("utf-8")
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("JSON 응답이 아님")
        return self._json


def patch_get(monkeypatch, response):
    """live_api._get 을 고정 응답 반환 함수로 교체. 호출 기록을 돌려준다."""
    calls = []

    async def _fake(url, params=None):
        calls.append((url, dict(params or {})))
        return response

    monkeypatch.setattr(api, "_get", _fake)
    return calls


def patch_get_error(monkeypatch):
    async def _fake(url, params=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(api, "_get", _fake)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def clear_cache():
    """테스트 간 캐시 격리."""
    api._cache.clear()
    yield
    api._cache.clear()


# ── /api/news ─────────────────────────────────────────────

NEWS_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>"제주" - Google 뉴스</title>
<item><title>첫 기사 - 제주의소리</title><link>https://news.google.com/a1</link>
  <source url="https://www.jejusori.net">제주의소리</source></item>
<item><title>둘째 기사</title><link>https://news.google.com/a2</link>
  <source url="https://x.com">한라일보</source></item>
<item><title>제목만있고링크없음</title><link></link>
  <source url="https://y.com">무시신문</source></item>
<item><title>셋째 기사 - 경향신문</title><link>https://news.google.com/a3</link>
  <source url="https://khan.co.kr">경향신문</source></item>
<item><title>넷째 기사</title><link>https://news.google.com/a4</link>
  <source url="https://z.com">제민일보</source></item>
<item><title>다섯째 기사(잘림)</title><link>https://news.google.com/a5</link>
  <source url="https://w.com">뉴시스</source></item>
</channel></rss>"""


def test_뉴스_상위4건_파싱과_제목_언론사_중복제거(monkeypatch):
    patch_get(monkeypatch, FakeResponse(text=NEWS_RSS))
    out = run(api.news())
    items = out["items"]
    assert len(items) == 4  # 링크 없는 항목은 건너뛰고 상위 4건만
    assert items[0] == {"title": "첫 기사", "url": "https://news.google.com/a1",
                        "source": "제주의소리"}  # " - 언론사" 접미어 제거
    assert items[1]["title"] == "둘째 기사"
    assert items[2]["title"] == "셋째 기사"  # 접미어 제거
    assert items[3]["source"] == "제민일보"
    assert all("다섯째" not in it["title"] for it in items)


def test_뉴스_30분캐시_재호출시_네트워크_생략(monkeypatch):
    calls = patch_get(monkeypatch, FakeResponse(text=NEWS_RSS))
    first = run(api.news())
    second = run(api.news())
    assert len(calls) == 1  # 두 번째는 캐시에서
    assert first == second


def test_뉴스_네트워크오류시_빈목록(monkeypatch):
    patch_get_error(monkeypatch)
    assert run(api.news()) == {"items": []}


def test_뉴스_파싱불가시_빈목록_그리고_캐시안함(monkeypatch):
    calls = patch_get(monkeypatch, FakeResponse(text="not xml at all <<<"))
    assert run(api.news()) == {"items": []}
    run(api.news())
    assert len(calls) == 2  # 실패 응답은 캐시하지 않고 재시도


# ── /api/live/detail ──────────────────────────────────────

class FakeTool:
    """BaseTool 대역 — label/enabled/run 만 흉내낸다."""

    def __init__(self, label, text, on=True):
        self.label = label
        self.name = label
        self._text = text
        self._on = on

    def enabled(self):
        return self._on

    async def run(self, **kwargs):
        if isinstance(self._text, Exception):
            raise self._text
        return self._text


def patch_detail_tools(monkeypatch, category, *tools):
    """_DETAIL_TOOLS[category] 를 고정 인스턴스를 돌려주는 팩토리로 교체."""
    mapping = dict(api._DETAIL_TOOLS)
    mapping[category] = tuple((lambda t=t: t) for t in tools)
    monkeypatch.setattr(api, "_DETAIL_TOOLS", mapping)


def test_상세_fuel은_두_도구_결과를_함께_반환(monkeypatch):
    patch_detail_tools(monkeypatch, "fuel",
                       FakeTool("제주 유가", "휘발유: 1743원/L"),
                       FakeTool("제주 주유소 가격", "성신주유소 1695원/L"))
    out = run(api.live_detail(category="fuel"))
    assert out["category"] == "fuel"
    assert out["items"] == [
        {"label": "제주 유가", "text": "휘발유: 1743원/L"},
        {"label": "제주 주유소 가격", "text": "성신주유소 1695원/L"},
    ]


def test_상세_실패항목은_제외되고_빈items_허용(monkeypatch):
    patch_detail_tools(monkeypatch, "weather",
                       FakeTool("제주공항 날씨", "제주공항 기상 조회 실패"),
                       FakeTool("보조", RuntimeError("boom")))
    out = run(api.live_detail(category="weather"))
    assert out == {"category": "weather", "items": []}


def test_상세_비활성_도구는_호출하지_않음(monkeypatch):
    patch_detail_tools(monkeypatch, "traffic",
                       FakeTool("꺼진 도구", "안 나와야 함", on=False),
                       FakeTool("제주 실시간 교통", "평균 45km/h"))
    out = run(api.live_detail(category="traffic"))
    assert [it["label"] for it in out["items"]] == ["제주 실시간 교통"]


def test_상세_5분캐시와_refresh_무시(monkeypatch):
    patch_detail_tools(monkeypatch, "traffic", FakeTool("교통", "1차 결과"))
    first = run(api.live_detail(category="traffic"))
    assert first["items"][0]["text"] == "1차 결과"

    # 결과가 바뀌어도 캐시가 살아 있으면 이전 값 반환
    patch_detail_tools(monkeypatch, "traffic", FakeTool("교통", "2차 결과"))
    cached = run(api.live_detail(category="traffic"))
    assert cached["items"][0]["text"] == "1차 결과"

    # refresh=1 이면 캐시를 무시하고 새로 조회 + 캐시 갱신
    fresh = run(api.live_detail(category="traffic", refresh=1))
    assert fresh["items"][0]["text"] == "2차 결과"
    again = run(api.live_detail(category="traffic"))
    assert again["items"][0]["text"] == "2차 결과"


def test_상세_카테고리별_캐시는_분리(monkeypatch):
    patch_detail_tools(monkeypatch, "fuel", FakeTool("유가", "유가 결과"))
    patch_detail_tools(monkeypatch, "traffic", FakeTool("교통", "교통 결과"))
    # patch_detail_tools 는 매핑을 통째로 바꾸므로 fuel 을 다시 세팅
    mapping = dict(api._DETAIL_TOOLS)
    mapping["fuel"] = ((lambda: FakeTool("유가", "유가 결과")),)
    monkeypatch.setattr(api, "_DETAIL_TOOLS", mapping)
    assert run(api.live_detail(category="fuel"))["items"][0]["text"] == "유가 결과"
    assert run(api.live_detail(category="traffic"))["items"][0]["text"] == "교통 결과"


# ── /api/live/density ─────────────────────────────────────

FAKE_SOURCES = {"jejudatahub": [
    {"name": "읍면동 단위 외국인 단기체류 유동인구", "apicode": "popcode"},
]}


def _density_row(emd, pop, city="제주시"):
    return {"baseDate": "20260401", "nationality": "중국",
            "city": city, "emd": emd, "visitPop": pop}


def setup_density(monkeypatch, months=("202606",)):
    monkeypatch.setattr(api, "load_sources", lambda: FAKE_SOURCES)
    monkeypatch.setattr(api.settings, "jejudatahub_project_key", "pk", raising=False)
    monkeypatch.setattr(api, "_recent_months", lambda n=8: list(months))


def test_밀집_집계_정렬_좌표매핑_level산정(monkeypatch):
    setup_density(monkeypatch)
    rows = [
        _density_row("연동", 63059),
        _density_row("노형동", 47040),
        _density_row("애월읍", 9686),
        _density_row("표선면", 7836, city="서귀포시"),
        _density_row("한림읍", 7740),
        _density_row("조천읍", 7264),
        _density_row("없는지역", 99999),   # 좌표 미매핑 → 제외
        _density_row("성산읍", None, city="서귀포시"),  # 값 없음 → 제외
    ]
    calls = patch_get(monkeypatch, FakeResponse(json_data={"totCnt": len(rows), "data": rows}))
    out = run(api.live_density())
    assert out["asof"] == "2026-06 기준"
    names = [p["name"] for p in out["points"]]
    assert names == ["연동", "노형동", "애월읍", "표선면", "한림읍", "조천읍"]
    # 6곳 → 값 순위 3등분: 상위 2곳=1, 중위 2곳=2, 하위 2곳=3
    assert [p["level"] for p in out["points"]] == [1, 1, 2, 2, 3, 3]
    top = out["points"][0]
    assert top["value"] == 63059
    assert (top["lat"], top["lng"]) == api._EMD_COORDS["연동"]
    # 요청 파라미터 규약: 날짜 + nationality 필터 + limit (number/page 금지)
    assert calls[0][1] == {"startDate": "202606", "endDate": "202606",
                           "nationality": "중국", "limit": 100}


def test_밀집_상위12곳으로_절단(monkeypatch):
    setup_density(monkeypatch)
    emds = list(api._EMD_COORDS)[:15]
    rows = [_density_row(emd, 1000 + i) for i, emd in enumerate(emds)]
    patch_get(monkeypatch, FakeResponse(json_data={"data": rows}))
    out = run(api.live_density())
    assert len(out["points"]) == 12
    # 12곳 → 4/4/4 등분
    assert [p["level"] for p in out["points"]] == [1] * 4 + [2] * 4 + [3] * 4
    values = [p["value"] for p in out["points"]]
    assert values == sorted(values, reverse=True)


def test_밀집_빈달은_건너뛰고_이전달로_폴백(monkeypatch):
    setup_density(monkeypatch, months=("202606", "202605", "202604"))
    rows = [_density_row("연동", 100)]
    calls = []

    async def _fake(url, params=None):
        calls.append(dict(params or {}))
        if params["startDate"] == "202604":
            return FakeResponse(json_data={"data": rows})
        return FakeResponse(json_data={"data": []})

    monkeypatch.setattr(api, "_get", _fake)
    out = run(api.live_density())
    assert out["asof"] == "2026-04 기준"
    assert [c["startDate"] for c in calls] == ["202606", "202605", "202604"]


def test_밀집_30분캐시(monkeypatch):
    setup_density(monkeypatch)
    calls = patch_get(monkeypatch, FakeResponse(
        json_data={"data": [_density_row("연동", 100)]}))
    first = run(api.live_density())
    second = run(api.live_density())
    assert len(calls) == 1
    assert first == second


def test_밀집_키없으면_빈응답(monkeypatch):
    monkeypatch.setattr(api.settings, "jejudatahub_project_key", None, raising=False)
    assert run(api.live_density()) == {"asof": None, "points": []}


def test_밀집_전체달_비면_빈응답_캐시안함(monkeypatch):
    setup_density(monkeypatch, months=("202606", "202605"))
    calls = patch_get(monkeypatch, FakeResponse(json_data={"data": []}))
    assert run(api.live_density()) == {"asof": None, "points": []}
    run(api.live_density())
    assert len(calls) == 4  # 2개월 x 2회 — 빈 결과는 캐시하지 않음


def test_밀집_네트워크오류시_빈응답(monkeypatch):
    setup_density(monkeypatch)
    patch_get_error(monkeypatch)
    assert run(api.live_density()) == {"asof": None, "points": []}
