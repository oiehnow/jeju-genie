"""에이전트 루프 단위 테스트 — 모의 프로바이더/스토어로 이벤트 흐름을 검증한다."""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.agent import run_agent  # noqa: E402
from app.tools.base import _TOOL_REGISTRY, BaseTool, register_tool  # noqa: E402


class FakeStore:
    """VectorStore 모의 — query가 미리 정해둔 hit을 반환."""

    def __init__(self, hits=None):
        self._hits = hits or []
        self.queries = []

    def query(self, text, top_k=None):
        self.queries.append(text)
        return self._hits


class ScriptedProvider:
    """라운드별로 미리 짜둔 이벤트를 재생하는 모의 프로바이더."""

    name = "scripted"
    supports_tools = True

    def __init__(self, rounds):
        self._rounds = list(rounds)
        self.calls = []  # (messages 스냅샷, tool_schemas) 기록

    async def available(self):
        return True

    async def stream_chat_with_tools(self, system, messages, tool_schemas):
        self.calls.append(([dict(m) for m in messages], list(tool_schemas or [])))
        for ev in self._rounds.pop(0):
            yield ev

    async def stream_chat(self, system, messages):
        for ev in self._rounds.pop(0):
            yield ev["content"]


def collect(agen):
    async def _run():
        return [e async for e in agen]

    return asyncio.run(_run())


@pytest.fixture
def dummy_live_tool():
    """항상 활성화되는 테스트용 라이브 도구 — 끝나면 레지스트리에서 제거."""

    @register_tool
    class DummyLiveTool(BaseTool):
        name = "dummy_live"
        label = "더미 라이브"
        theme = "stats"
        description = "테스트용 더미 도구"

        def enabled(self) -> bool:
            return True

        async def run(self, **kwargs) -> str:
            return "더미 실시간 값 42"

    yield DummyLiveTool
    _TOOL_REGISTRY.pop("dummy_live", None)


@pytest.fixture
def dummy_map_tool():
    """refs/map_points 수집기를 채우는 테스트용 장소 도구."""

    @register_tool
    class DummyMapTool(BaseTool):
        name = "dummy_map"
        label = "더미 장소"
        theme = "place"
        description = "테스트용 지도 도구"

        def enabled(self) -> bool:
            return True

        async def run(self, **kwargs) -> str:
            self.refs.append({"title": "성산일출봉 안내", "url": "https://example.com/place"})
            self.map_points.append({"name": "성산일출봉", "lat": 33.4581, "lng": 126.9425})
            # 같은 좌표 중복 — 에이전트가 map 이벤트에서 제거해야 한다
            self.map_points.append({"name": "성산일출봉 중복", "lat": 33.4581, "lng": 126.9425})
            return "성산일출봉 위치 정보"

    yield DummyMapTool
    _TOOL_REGISTRY.pop("dummy_map", None)


HIT = {
    "text": "성산일출봉은 유네스코 세계자연유산이다.",
    "metadata": {"title": "성산일출봉", "source": "seed", "url": "https://example.com/seongsan"},
    "distance": 0.1,
}


def test_direct_answer_without_tools():
    """도구 호출 없이 바로 답변 — token 이벤트 후 sources(폴백)/done."""
    provider = ScriptedProvider([
        [{"type": "content", "content": "안녕"}, {"type": "content", "content": "하세요"}],
    ])
    events = collect(run_agent(provider, "안녕", [], FakeStore()))

    assert [e["type"] for e in events] == ["token", "token", "sources", "done"]
    assert "".join(e["content"] for e in events if e["type"] == "token") == "안녕하세요"
    # 도구를 하나도 안 쓴 잡담 — '항상 출처 첨부' 정책: 질문 기반 네이버 검색 링크 1개 폴백
    src = events[-2]["sources"]
    assert len(src) == 1
    assert src[0]["title"] == "안녕"  # 질문 앞 20자
    assert src[0]["source"] == "네이버 검색"
    assert "search.naver.com" in src[0]["url"]
    # 1라운드 호출에 도구 스키마(최소한 지식 검색 도구)가 붙었는지
    assert any(
        s["function"]["name"] == "search_jeju_knowledge" for s in provider.calls[0][1]
    )


def test_one_tool_round_then_answer(dummy_live_tool):
    """1라운드 도구(라이브+지식검색) 실행 후 답변 — status/live/sources 이벤트 검증."""
    provider = ScriptedProvider([
        [{
            "type": "tool_calls",
            "tool_calls": [
                {"id": "c1", "name": "dummy_live", "arguments": "{}"},
                {"id": "c2", "name": "search_jeju_knowledge",
                 "arguments": json.dumps({"query": "성산일출봉"}, ensure_ascii=False)},
            ],
        }],
        [{"type": "content", "content": "성산일출봉 답변"}],
    ])
    store = FakeStore(hits=[HIT])
    events = collect(run_agent(provider, "성산일출봉 알려줘", [], store))

    types = [e["type"] for e in events]
    assert types == ["status", "status", "live", "token", "sources", "done"]

    statuses = [e for e in events if e["type"] == "status"]
    assert statuses[0] == {"type": "status", "tool": "dummy_live",
                           "label": "더미 라이브", "theme": "stats"}
    assert statuses[1]["tool"] == "search_jeju_knowledge"
    assert statuses[1]["theme"] == "knowledge"

    # live 배지: 실제 값을 낸 라이브 도구만 (지식 검색은 sources로 표현되므로 제외)
    live = next(e for e in events if e["type"] == "live")
    assert live["live"] == [{"name": "dummy_live", "label": "더미 라이브"}]

    # sources: 지식 검색 도구의 hits 기반
    sources = next(e for e in events if e["type"] == "sources")
    assert sources["sources"] == [{
        "title": "성산일출봉", "source": "seed", "url": "https://example.com/seongsan",
    }]
    assert store.queries == ["성산일출봉"]

    # 2라운드 호출 메시지에 assistant(tool_calls) + tool 결과가 붙었는지
    second_msgs = provider.calls[1][0]
    roles = [m["role"] for m in second_msgs]
    assert roles == ["user", "assistant", "tool", "tool"]
    tool_msgs = [m for m in second_msgs if m["role"] == "tool"]
    assert tool_msgs[0]["tool_call_id"] == "c1"
    assert "더미 실시간 값 42" in tool_msgs[0]["content"]
    assert "성산일출봉" in tool_msgs[1]["content"]


def test_event_order_live_before_first_token(dummy_live_tool):
    """live 이벤트는 최종 답변의 첫 token보다 반드시 먼저 1회만 온다."""
    provider = ScriptedProvider([
        [{"type": "tool_calls",
          "tool_calls": [{"id": "c1", "name": "dummy_live", "arguments": "{}"}]}],
        [{"type": "content", "content": "답변1"}, {"type": "content", "content": "답변2"}],
    ])
    events = collect(run_agent(provider, "질문", [], FakeStore()))

    types = [e["type"] for e in events]
    assert types.count("live") == 1
    assert types.index("live") < types.index("token")
    assert types[-2:] == ["sources", "done"]


def test_max_rounds_forces_final_answer_without_tools(dummy_live_tool, monkeypatch):
    """도구를 계속 부르면 max_rounds 이후 도구 없이 마지막 호출을 강제한다."""
    from app.config import settings

    monkeypatch.setattr(settings, "agent_max_rounds", 2)
    tool_round = [{"type": "tool_calls",
                   "tool_calls": [{"id": "c", "name": "dummy_live", "arguments": "{}"}]}]
    provider = ScriptedProvider([
        tool_round, tool_round,  # 1~2라운드: 계속 도구 호출
        [{"type": "content", "content": "최종 답변"}],  # 3번째 호출: 도구 없이
    ])
    events = collect(run_agent(provider, "질문", [], FakeStore()))

    assert [e["type"] for e in events if e["type"] == "token"] == ["token"]
    assert events[-1] == {"type": "done"}
    # 마지막 호출에는 도구 스키마가 비어 있어야 한다
    assert provider.calls[0][1] and provider.calls[1][1]
    assert provider.calls[2][1] == []


def test_fallback_provider_without_tool_support():
    """supports_tools=False 프로바이더는 RAG 프리페치 + 단순 스트리밍 경로를 탄다."""

    class SimpleProvider:
        name = "simple"
        supports_tools = False

        async def available(self):
            return True

        async def stream_chat(self, system, messages):
            assert "성산일출봉" in system  # 프리페치된 hit이 프롬프트에 들어갔는지
            yield "폴백 "
            yield "답변"

    store = FakeStore(hits=[HIT])
    events = collect(run_agent(SimpleProvider(), "성산일출봉?", [], store))

    assert [e["type"] for e in events] == ["token", "token", "sources", "done"]
    assert store.queries == ["성산일출봉?"]
    sources = next(e for e in events if e["type"] == "sources")
    assert sources["sources"][0]["title"] == "성산일출봉"


def test_map_and_merged_sources(dummy_map_tool):
    """도구 refs/map_points 회수 → map 이벤트(좌표 중복 제거) + 통합 sources 검증.

    같은 도구를 2라운드 연속 호출해 회수 후 clear 로 이중 집계가 없는지도 본다.
    """
    provider = ScriptedProvider([
        [{
            "type": "tool_calls",
            "tool_calls": [
                {"id": "c1", "name": "dummy_map", "arguments": "{}"},
                {"id": "c2", "name": "search_jeju_knowledge",
                 "arguments": json.dumps({"query": "성산일출봉"}, ensure_ascii=False)},
            ],
        }],
        [{"type": "tool_calls",
          "tool_calls": [{"id": "c3", "name": "dummy_map", "arguments": "{}"}]}],
        [{"type": "content", "content": "성산일출봉 답변"}],
    ])
    events = collect(run_agent(provider, "성산일출봉 어디야", [], FakeStore(hits=[HIT])))

    types = [e["type"] for e in events]
    # SSE 계약: status → live → token → map → sources → done
    assert types == ["status", "status", "status", "live", "token", "map", "sources", "done"]
    assert types.index("map") > types.index("token")
    assert types.index("map") < types.index("sources")

    # map: 2라운드 x 2개(중복 좌표 포함) = 4개 수집 → 좌표 중복 제거로 1개
    map_ev = next(e for e in events if e["type"] == "map")
    assert map_ev["points"] == [{"name": "성산일출봉", "lat": 33.4581, "lng": 126.9425}]

    # sources: 지식 hits + 도구 refs 통합, ref 는 2라운드 호출에도 1개로 중복 제거
    sources = next(e for e in events if e["type"] == "sources")["sources"]
    assert sources == [
        {"title": "성산일출봉", "source": "seed", "url": "https://example.com/seongsan"},
        {"title": "성산일출봉 안내", "source": "더미 장소", "url": "https://example.com/place"},
    ]


def test_map_event_absent_without_points(dummy_live_tool):
    """map_points 를 안 채운 도구만 쓰면 map 이벤트는 나가지 않는다."""
    provider = ScriptedProvider([
        [{"type": "tool_calls",
          "tool_calls": [{"id": "c1", "name": "dummy_live", "arguments": "{}"}]}],
        [{"type": "content", "content": "답변"}],
    ])
    events = collect(run_agent(provider, "질문", [], FakeStore()))
    assert "map" not in [e["type"] for e in events]


# ── /api/suggest ──────────────────────────────────────────


class _SuggestProvider:
    """complete_json 을 가진 모의 프로바이더 — 반환값/예외를 주입한다."""

    name = "mock"

    def __init__(self, raw=None, error=None):
        self._raw, self._error = raw, error

    async def available(self):
        return True

    async def complete_json(self, system, user, model=None, max_tokens=1000):
        if self._error:
            raise self._error
        return self._raw


def _suggest_client(monkeypatch, provider):
    import app.main as main

    monkeypatch.setattr(main, "get_provider", lambda: provider)
    return TestClient(main.app)


def test_suggest_returns_empty_on_llm_failure(monkeypatch):
    """LLM 호출이 실패해도 500 없이 빈 배열을 반환한다."""
    client = _suggest_client(monkeypatch, _SuggestProvider(error=RuntimeError("boom")))
    r = client.post("/api/suggest", json={"question": "성산일출봉?", "answer": "유네스코 유산"})
    assert r.status_code == 200
    assert r.json() == {"suggestions": []}


def test_suggest_returns_empty_without_helper(monkeypatch):
    """complete_json 이 없는 프로바이더(예: Ollama)면 빈 배열."""

    class NoHelperProvider:
        name = "plain"

        async def available(self):
            return True

    client = _suggest_client(monkeypatch, NoHelperProvider())
    r = client.post("/api/suggest", json={"question": "질문", "answer": "답변"})
    assert r.status_code == 200
    assert r.json() == {"suggestions": []}


def test_suggest_parses_json_array(monkeypatch):
    """모델이 코드펜스를 붙여도 JSON 배열만 뽑아 최대 3개를 반환한다."""
    raw = '```json\n["우도 가는 법?", "일출 명소는?", "근처 맛집은?", "네번째"]\n```'
    client = _suggest_client(monkeypatch, _SuggestProvider(raw=raw))
    r = client.post("/api/suggest", json={"question": "성산일출봉?", "answer": "유네스코 유산"})
    assert r.status_code == 200
    assert r.json() == {"suggestions": ["우도 가는 법?", "일출 명소는?", "근처 맛집은?"]}
