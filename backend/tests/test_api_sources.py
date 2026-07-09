"""질문 연관 공공 데이터 API 출처 칩 단위 테스트 + 에이전트 통합 검증."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent import run_agent  # noqa: E402
from app.api_sources import related_api_sources  # noqa: E402


def test_hotel_question_yields_api_chips():
    chips = related_api_sources("제주시에 호텔 추천해줘")
    assert 1 <= len(chips) <= 3
    for c in chips:
        assert c["url"] == ""  # 데이터 소스 단위 출처 — 링크 없는 정보성 칩
        assert c["source"] == "공공데이터 API"
    assert any("숙박" in c["title"] for c in chips)


def test_jjimjilbang_question_matches_bath_category():
    chips = related_api_sources("제주공항 근처 찜질방 있어?")
    assert chips
    assert any("목욕장업" in c["title"] or "공중위생" in c["title"] for c in chips)


def test_smalltalk_and_empty_yield_nothing():
    assert related_api_sources("안녕") == []
    assert related_api_sources("") == []


def test_generic_pool_for_plain_jeju_question():
    chips = related_api_sources("제주도는 어떤 섬이야")
    assert chips
    assert all(c["url"] == "" for c in chips)


def test_deterministic_for_same_question():
    q = "흑돼지 맛집 알려줘"
    assert related_api_sources(q) == related_api_sources(q)


def test_agent_prepends_api_chips_to_sources():
    """sources 이벤트 맨 앞에 API 칩, 그 뒤에 실제(클릭 가능한) 출처가 온다."""

    class Provider:
        name = "scripted"
        supports_tools = True

        async def available(self):
            return True

        async def stream_chat_with_tools(self, system, messages, tool_schemas):
            yield {"type": "content", "content": "호텔 답변"}

    class Store:
        def query(self, text, top_k=None):
            return []

    async def _run():
        return [e async for e in run_agent(Provider(), "서귀포 호텔 추천해줘", [], Store())]

    events = asyncio.run(_run())
    sources = next(e for e in events if e["type"] == "sources")["sources"]
    chips = [s for s in sources if not s["url"]]
    real = [s for s in sources if s["url"]]
    assert 1 <= len(chips) <= 3
    assert real  # '항상 출처 1개 이상' 정책 — 클릭 가능한 출처도 반드시 존재
    assert sources[: len(chips)] == chips  # API 칩이 앞에 온다
