"""하이브리드 검색 라이브 도구 — Visit Jeju 콘텐츠 검색 + 한국어 위키백과.

RAG 인덱스(정적 스냅샷)와 별개로, 질의 시점에 원본 소스를 직접 검색한다.
- visitjeju_search: 제주관광공사 최신 콘텐츠(관광지/음식점/숙박/축제 등) 키워드 검색
- jeju_wiki_search: 한국어 위키백과 백과 지식 검색 (키 불요)

실측 확인 사항 (2026-07 curl 검증):
- searchList 는 title= 파라미터가 제목 부분일치 검색으로 동작한다 (성산 → 67건).
- category= 파라미터로 contentscd(c1~c6) 필터가 가능하며 title 과 조합된다.
- 각 item 에 latitude/longitude 필드가 있어 지도 마커로 바로 쓸 수 있다.
"""
from urllib.parse import quote

import httpx

from app.config import settings
from app.tools.base import BaseTool, register_tool

# jeju_live 와 동일한 패턴 — 테스트에서 이 모듈의 _get 을 갈아끼워 네트워크를 차단한다.
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
# 위키미디어 봇 정책: 축약형 브라우저 UA 는 403 — 식별 가능한 UA 필수 (실측 확인)
_WIKI_UA = {"User-Agent": "JejuGenieBot/1.0 (jeju-genie RAG chatbot; oiehnow@gmail.com)"}


async def _get(url: str, params: dict | None = None,
               headers: dict | None = None) -> httpx.Response:
    async with httpx.AsyncClient(timeout=20, verify=False,
                                 follow_redirects=True, headers=headers or _UA) as c:
        return await c.get(url, params=params or {})


@register_tool
class VisitJejuSearchTool(BaseTool):
    name = "visitjeju_search"
    label = "제주 관광 검색"
    theme = "place"
    description = ("제주 관광지/맛집/카페/숙소/축제를 최신 데이터베이스에서 검색한다. "
                   "장소 추천, 맛집, 볼거리, 갈 곳 질문에 사용.")
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "검색 키워드 (예: 성산, 흑돼지, 오름)"},
            "category": {
                "type": "string",
                "enum": ["관광지", "쇼핑", "숙박", "음식점", "축제/행사", "테마여행"],
                "description": "콘텐츠 분류 필터 (선택). 맛집/카페는 음식점, 호텔/펜션은 숙박",
            },
        },
        "required": ["query"],
    }
    # 실측: category=c1~c6 이 contentscd 필터로 동작 (c1 관광지 / c2 쇼핑 / c3 숙박 / c4 음식점 / c5 축제·행사 / c6 테마여행)
    _CATEGORY = {"관광지": "c1", "쇼핑": "c2", "숙박": "c3",
                 "음식점": "c4", "축제/행사": "c5", "테마여행": "c6"}

    def enabled(self) -> bool:
        return bool(settings.visitjeju_api_key)

    async def run(self, query: str = "", category: str = "", **kwargs) -> str:
        if not query:
            return "검색어가 필요합니다."
        params = {"apiKey": settings.visitjeju_api_key, "locale": "kr", "title": query}
        cat_code = self._CATEGORY.get(category or "")
        if cat_code:
            params["category"] = cat_code
        try:
            r = await _get("https://api.visitjeju.net/vsjApi/contents/searchList", params)
        except httpx.HTTPError:
            return f"'{query}' 관광 콘텐츠 검색 실패 (네트워크 오류)"
        try:
            body = r.json()
        except ValueError:
            return f"'{query}' 관광 콘텐츠 검색 실패"
        items = body.get("items") or []
        if not items:
            hint = f" (분류: {category})" if cat_code else ""
            return f"'{query}'{hint} 관광 콘텐츠 검색 결과가 없습니다."
        parts = []
        for it in items[:5]:
            title = it.get("title", "이름미상")
            label = (it.get("contentscd") or {}).get("label", "")
            addr = it.get("roadaddress") or it.get("address") or ""
            intro = it.get("introduction") or ""
            seg = f"{title}"
            if label:
                seg += f" [{label}]"
            if addr:
                seg += f" — {addr}"
            if intro:
                seg += f" | {intro}"
            parts.append(seg)
            # 출처 칩: Visit Jeju 상세 페이지
            cid = it.get("contentsid", "")
            if cid:
                self.refs.append({
                    "title": title,
                    "url": f"https://www.visitjeju.net/kr/detail/view?contentsid={cid}",
                })
            # 지도 마커: 실측 확인된 latitude/longitude 필드
            lat, lng = it.get("latitude"), it.get("longitude")
            if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
                self.map_points.append({"name": title, "lat": float(lat), "lng": float(lng)})
        total = body.get("totalCount", len(items))
        return (f"Visit Jeju '{query}' 검색 결과 {total}건 중 상위 {len(parts)}건 — "
                + "; ".join(parts))


@register_tool
class JejuWikiSearchTool(BaseTool):
    name = "jeju_wiki_search"
    label = "제주 지식 아카이브"
    theme = "knowledge"
    description = ("제주의 역사, 지리, 문화, 인물, 자연 등 백과 지식을 검색한다. "
                   "세부 사실이나 배경 지식이 필요할 때 사용.")
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "검색할 주제 (예: 한라산, 4.3 사건, 해녀)"},
        },
        "required": ["query"],
    }

    def enabled(self) -> bool:
        # 공개 API — 키 불요, 항상 사용 가능
        return True

    async def run(self, query: str = "", **kwargs) -> str:
        if not query:
            return "검색어가 필요합니다."
        # 제주 문맥을 강제 — 검색어에 '제주'가 없으면 붙여서 검색
        term = query if "제주" in query else f"제주 {query}"
        try:
            r = await _get("https://ko.wikipedia.org/w/api.php",
                           {"action": "query", "list": "search", "srsearch": term,
                            "format": "json", "srlimit": 3},
                           headers=_WIKI_UA)
        except httpx.HTTPError:
            return f"'{query}' 위키백과 검색 실패 (네트워크 오류)"
        try:
            results = r.json().get("query", {}).get("search", [])
        except ValueError:
            results = []
        if not results:
            return f"'{query}' 위키백과 검색 결과가 없습니다."
        blocks = []
        for s in results[:3]:
            title = s.get("title", "")
            if not title:
                continue
            extract, page_url = "", ""
            # 문서 요약은 REST summary 엔드포인트에서 — 실패해도 제목만으로 계속 진행
            try:
                sr = await _get(f"https://ko.wikipedia.org/api/rest_v1/page/summary/{quote(title)}",
                                headers=_WIKI_UA)
                sd = sr.json()
                extract = sd.get("extract") or ""
                page_url = (sd.get("content_urls") or {}).get("desktop", {}).get("page", "")
            except (httpx.HTTPError, ValueError):
                pass
            if not page_url:
                page_url = f"https://ko.wikipedia.org/wiki/{quote(title)}"
            self.refs.append({"title": f"위키백과: {title}", "url": page_url})
            blocks.append(f"[{title}] {extract}" if extract else f"[{title}]")
        if not blocks:
            return f"'{query}' 위키백과 검색 결과가 없습니다."
        return f"위키백과 '{term}' 검색 요약 — " + " / ".join(blocks)
