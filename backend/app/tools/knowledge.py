"""RAG 지식 검색 도구 — 벡터 인덱스 검색을 에이전트 도구로 노출한다.

기존에는 chat 요청마다 무조건 프리페치하던 RAG 검색을 도구화해,
LLM이 필요할 때만 원하는 검색어로 호출하게 한다.
store 는 요청 스코프에서 주입되므로(에이전트가 요청마다 새 인스턴스 생성),
store 없이 만들어지면 enabled()=False 로 일반 도구 목록에서 빠진다.
"""
import asyncio

from app.tools.base import BaseTool, register_tool


@register_tool
class SearchJejuKnowledgeTool(BaseTool):
    name = "search_jeju_knowledge"
    label = "제주 지식 검색"
    theme = "knowledge"
    description = (
        "제주 지식 베이스(관광지 상세, 문화, 역사, 축제, 자연 등 문서화된 정보)를 "
        "의미 검색한다. 제주의 세부 지식이 필요한 질문에 사용. "
        "검색어는 한국어 핵심 키워드 위주로."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "검색할 내용 (예: 성산일출봉 일출 명소)",
            }
        },
        "required": ["query"],
    }

    def __init__(self, store=None):
        super().__init__()
        self.store = store
        # 이 요청에서 검색된 원본 hit 누적 — 에이전트가 sources 이벤트로 내보낸다.
        self.hits: list[dict] = []

    def enabled(self) -> bool:
        return self.store is not None

    async def run(self, query: str = "", **kwargs) -> str:
        if not self.store or not query:
            return "검색어가 필요합니다."
        # Chroma 질의는 동기 코드이므로 스레드로 넘겨 이벤트 루프를 막지 않는다.
        hits = await asyncio.to_thread(self.store.query, query)
        if not hits:
            return f"'{query}' 관련 자료를 지식 베이스에서 찾지 못했습니다."
        self.hits.extend(hits)
        blocks = []
        for i, h in enumerate(hits, 1):
            meta = h.get("metadata", {})
            head = meta.get("title") or meta.get("source", "")
            blocks.append(f"[{i}] {head}\n{h['text']}")
        return "\n\n".join(blocks)
