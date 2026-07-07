"""도구 실행 런타임 — chat 흐름에서 호출.

1) 활성 도구 스키마를 LLM에 주고 어떤 도구를 부를지 결정(decide_tool_calls)
2) 선택된 도구를 실행해 결과 텍스트를 모아 반환 → 시스템 프롬프트 [실시간 데이터]로 주입

도구가 없거나(전부 비활성) LLM이 함수호출을 안 하면 빈 문자열.
"""
import logging

from app.tools.base import enabled_tools

logger = logging.getLogger("jeju-genie.tools")


async def run_live_tools(provider, message: str) -> str:
    tools = {t.name: t for t in enabled_tools()}
    if not tools:
        return ""
    schemas = [t.openai_schema() for t in tools.values()]
    try:
        calls = await provider.decide_tool_calls(message, schemas)
    except Exception:
        logger.exception("도구 선택 실패")
        return ""

    results: list[str] = []
    for name, args in calls:
        tool = tools.get(name)
        if not tool:
            continue
        try:
            out = tool.run(**args)
            if out:
                results.append(f"## {tool.name}\n{out}")
        except Exception as e:
            logger.warning("도구 '%s' 실행 실패: %s", name, e)
            results.append(f"## {tool.name}\n(조회 실패: {type(e).__name__})")
    return "\n\n".join(results)
