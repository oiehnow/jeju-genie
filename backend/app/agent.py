"""스트리밍 tool-calling 에이전트 루프.

기존 3단계(RAG 프리페치 → 비스트리밍 도구선택 호출 → 답변 스트리밍)를
단일 스트리밍 루프로 교체한다: 도구 스키마를 붙여 스트리밍 호출하고,
content 델타는 즉시 토큰으로 내보내며, tool_calls 로 끝나면 도구를 병렬
실행해 tool 메시지로 붙인 뒤 재호출한다. 첫 토큰까지 LLM 왕복이 1번이 된다.

yield 하는 이벤트 (main.py가 SSE로 직렬화 — 프론트와 합의된 계약, 변경 금지):
- {"type": "status", "tool": str, "label": str, "theme": str} : 도구 실행 시작마다
- {"type": "live", "live": [{"name", "label"}]}               : 최종 답변 전 1회
- {"type": "token", "content": str}                            : 답변 텍스트 델타
- {"type": "map", "points": [{"name", "lat", "lng"}]}          : 지도 마커 (있을 때만 1회)
- {"type": "sources", "sources": [{"title", "source", "url"}]} : 통합 출처 (항상 1개 이상)
- {"type": "done"}
"""
import asyncio
import inspect
import json
import logging
from typing import AsyncIterator
from urllib.parse import quote

from app.api_sources import related_api_sources
from app.config import settings
from app.prompts import AGENT_TOOL_GUIDE, SYSTEM_PROMPT, build_system_prompt
from app.tools.base import BaseTool, discover_tools
from app.tools.knowledge import SearchJejuKnowledgeTool

logger = logging.getLogger("jeju-genie.agent")


def _source_link(url: str, title: str) -> str:
    """출처를 클릭 가능한 링크로. 커넥터가 준 사용자용 상세 URL이 있으면 그대로,
    없거나 내부 API 프록시 URL이면 제목으로 네이버 검색 링크를 만들어 항상 클릭되게 한다."""
    if url and url.startswith("http") and "api/proxy" not in url:
        return url
    q = quote(f"제주 {title}".strip()) if title else quote("제주")
    return f"https://search.naver.com/search.naver?query={q}"


def _dedupe_sources(hits: list[dict]) -> list[dict]:
    """hit 목록 → 프론트 출처 카드 형식으로 변환 + 중복 제거 (순서 유지)."""
    seen, uniq = set(), []
    for h in hits:
        meta = h.get("metadata", {})
        s = {
            "title": meta.get("title", ""),
            "source": meta.get("source", ""),
            "url": _source_link(meta.get("url", ""), meta.get("title", "")),
        }
        key = (s["title"], s["source"])
        if key not in seen:
            seen.add(key)
            uniq.append(s)
    return uniq


def _dedupe_points(points: list[dict]) -> list[dict]:
    """지도 마커 목록 → 제주 범위 밖 제거 + 같은 좌표 제거 + 최대 10개 (순서 유지)."""
    seen, uniq = set(), []
    for p in points:
        try:
            lat, lng = float(p.get("lat")), float(p.get("lng"))
        except (TypeError, ValueError):
            continue
        # 제주 좌표 범위 (마라도~추자도) 밖 마커는 버린다 — 육지 동명 업소 오탐 방지
        if not (32.9 <= lat <= 34.1 and 125.9 <= lng <= 127.1):
            continue
        key = (round(lat, 6), round(lng, 6))
        if key in seen:
            continue
        seen.add(key)
        uniq.append({"name": p.get("name", ""), "lat": lat, "lng": lng})
        if len(uniq) >= 10:
            break
    return uniq


def _merge_sources(hits: list[dict], tool_refs: list[tuple[str, dict]], question: str) -> list[dict]:
    """지식 검색 hits + 도구 refs 를 하나의 출처 목록으로 통합한다.

    tool_refs 항목은 (도구 label, {"title", "url"}). 비어 있으면 사용자 질문의
    네이버 검색 링크 1개로 폴백한다 — '답변에는 항상 출처를 첨부' 정책.
    """
    sources = _dedupe_sources(hits)
    seen = {(s["title"], s["url"]) for s in sources}
    for label, ref in tool_refs:
        title = ref.get("title", "")
        s = {"title": title, "source": label, "url": _source_link(ref.get("url", ""), title)}
        key = (s["title"], s["url"])
        if key not in seen:
            seen.add(key)
            sources.append(s)
    if not sources:
        title = (question or "").strip()[:20] or "제주"
        sources = [{"title": title, "source": "네이버 검색", "url": _source_link("", title)}]
    return sources


def _build_tools(store) -> tuple[dict[str, BaseTool], SearchJejuKnowledgeTool]:
    """요청마다 새 도구 인스턴스를 만든다.

    지식 검색 도구는 요청 스코프의 store 를 주입해야 하므로 별도로 생성하고,
    나머지 라이브 도구는 레지스트리에서 활성화된 것만 인스턴스화한다.
    """
    tools: dict[str, BaseTool] = {}
    for name, cls in discover_tools().items():
        if name == SearchJejuKnowledgeTool.name:
            continue  # store 없이 만들어지는 인스턴스는 건너뛰고 아래에서 주입 생성
        inst = cls()
        if inst.enabled():
            tools[name] = inst
    knowledge = SearchJejuKnowledgeTool(store=store)
    if knowledge.enabled():
        tools[knowledge.name] = knowledge
    return tools, knowledge


async def _exec_tool(tool: BaseTool, args: dict) -> tuple[str, bool]:
    """도구 하나 실행. (결과 텍스트, 성공 여부) 반환 — 실패해도 루프는 계속."""
    try:
        out = tool.run(**args)
        # 도구 계약은 async run 이지만, 아직 동기 run 인 도구가 남아 있어도 수용한다.
        if inspect.isawaitable(out):
            out = await out
        return (out or "(결과 없음)", bool(out))
    except Exception as e:
        logger.warning("도구 '%s' 실행 실패: %s", tool.name, e)
        return (f"(조회 실패: {type(e).__name__})", False)


async def run_agent(provider, message: str, history: list[dict], store) -> AsyncIterator[dict]:
    """스트리밍 에이전트 루프. dict 이벤트를 yield 하고 main.py가 SSE로 직렬화한다."""
    if not getattr(provider, "supports_tools", False):
        # 함수호출 미지원 프로바이더(Ollama)는 기존 방식 유지: RAG 프리페치 + 단순 스트리밍
        async for event in _run_simple(provider, message, history, store):
            yield event
        return

    tools, knowledge_tool = _build_tools(store)
    schemas = [t.openai_schema() for t in tools.values()]
    system = SYSTEM_PROMPT + "\n" + AGENT_TOOL_GUIDE
    messages: list[dict] = [*history, {"role": "user", "content": message}]

    live_used: list[dict] = []  # 실제 값을 낸 라이브 도구 누적 (UI 배지)
    live_sent = False
    tool_refs: list[tuple[str, dict]] = []  # (도구 label, ref) — 요청 단위 출처 누적
    map_points: list[dict] = []             # 도구가 남긴 지도 마커 누적
    max_rounds = settings.agent_max_rounds
    round_no = 0

    while True:
        # 라운드 초과 시 도구 없이 마지막 호출 → 답변을 강제한다.
        round_schemas = schemas if round_no < max_rounds else []
        tool_calls: list[dict] = []
        round_text: list[str] = []
        try:
            async for ev in provider.stream_chat_with_tools(system, messages, round_schemas):
                if ev["type"] == "content":
                    # 최종 답변 토큰이 시작되기 전에 라이브 배지를 1회 내보낸다.
                    if live_used and not live_sent:
                        yield {"type": "live", "live": live_used}
                        live_sent = True
                    round_text.append(ev["content"])
                    yield {"type": "token", "content": ev["content"]}
                elif ev["type"] == "tool_calls":
                    tool_calls = ev["tool_calls"]
        except Exception as e:
            logger.exception("LLM stream error")
            yield {"type": "token", "content": f"앗, 지니가 잠깐 말을 잃었어요… ({type(e).__name__})"}
            break

        if not tool_calls or round_no >= max_rounds:
            break  # 도구 호출 없이 끝났거나 라운드 초과 → 답변 완료
        round_no += 1

        # 모델이 낸 tool_calls 를 assistant 메시지로 대화에 기록
        messages.append({
            "role": "assistant",
            "content": "".join(round_text) or None,
            "tool_calls": [
                {
                    "id": c["id"],
                    "type": "function",
                    "function": {"name": c["name"], "arguments": c["arguments"] or "{}"},
                }
                for c in tool_calls
            ],
        })

        # 실행할 도구를 모으고, 각 실행 직전 status 이벤트를 먼저 내보낸다.
        planned: list[tuple[dict, BaseTool | None, dict]] = []
        for call in tool_calls:
            tool = tools.get(call["name"])
            if tool is None:
                planned.append((call, None, {}))
                continue
            try:
                args = json.loads(call["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            yield {
                "type": "status",
                "tool": tool.name,
                "label": tool.label or tool.name,
                "theme": tool.theme,
            }
            planned.append((call, tool, args))

        # 선택된 도구들을 병렬 실행
        results = await asyncio.gather(
            *(_exec_tool(tool, args) for _, tool, args in planned if tool is not None)
        )
        it = iter(results)
        for call, tool, _args in planned:
            if tool is None:
                text, ok = f"(알 수 없는 도구: {call['name']})", False
            else:
                text, ok = next(it)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": text})
            # 지식 검색은 sources 이벤트로 표현되므로 '실시간 데이터' 배지에서는 제외
            if ok and tool is not None and tool.theme != "knowledge":
                if not any(u["name"] == tool.name for u in live_used):
                    live_used.append({"name": tool.name, "label": tool.label or tool.name})

        # 이번 라운드 도구 인스턴스의 refs/map_points 회수 — 같은 도구가 다음
        # 라운드에 또 불려도 이중 집계되지 않도록 회수 즉시 비운다.
        harvested: set[int] = set()
        for _call, tool, _args in planned:
            if tool is None or id(tool) in harvested:
                continue
            harvested.add(id(tool))
            label = tool.label or tool.name
            tool_refs.extend((label, dict(r)) for r in tool.refs)
            tool.refs.clear()
            map_points.extend(dict(p) for p in tool.map_points)
            tool.map_points.clear()

    points = _dedupe_points(map_points)
    if points:
        yield {"type": "map", "points": points}
    # 질문 연관 공공 API 칩(정보성)을 실제 출처 앞에 붙인다
    sources = related_api_sources(message) + _merge_sources(knowledge_tool.hits, tool_refs, message)
    yield {"type": "sources", "sources": sources}
    yield {"type": "done"}


async def _run_simple(provider, message: str, history: list[dict], store) -> AsyncIterator[dict]:
    """Ollama 폴백 경로 — RAG 프리페치 + build_system_prompt 로 단순 스트리밍."""
    hits = await asyncio.to_thread(store.query, message)
    system = build_system_prompt(hits, "")
    messages = [*history, {"role": "user", "content": message}]
    try:
        async for token in provider.stream_chat(system, messages):
            yield {"type": "token", "content": token}
    except Exception as e:
        logger.exception("LLM stream error")
        yield {"type": "token", "content": f"앗, 지니가 잠깐 말을 잃었어요… ({type(e).__name__})"}
    yield {"type": "sources",
           "sources": related_api_sources(message) + _merge_sources(hits, [], message)}
    yield {"type": "done"}
