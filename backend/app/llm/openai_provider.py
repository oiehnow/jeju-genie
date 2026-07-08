"""OpenAI(GPT) 프로바이더 — OPENAI_API_KEY가 설정되면 활성화.

키가 없으면 available()=False → factory가 Ollama로 폴백.
함수호출(tool-calling)을 지원하므로 chat 흐름은 에이전트 루프(app.agent)를 탄다.
"""
from typing import AsyncIterator

from app.config import settings
from app.llm.base import LLMProvider


class OpenAIProvider(LLMProvider):
    name = "openai"
    supports_tools = True

    def __init__(self):
        self._client = None

    def _client_lazy(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        return self._client

    async def available(self) -> bool:
        return bool(settings.openai_api_key)

    @staticmethod
    def _completion_kwargs(model: str | None = None, max_tokens: int | None = None) -> dict:
        """모델 계열별 토큰/추론 파라미터 분기 (모든 완성 호출 공용).

        gpt-5/o-계열 추론 모델은 max_tokens 대신 max_completion_tokens 를 요구하고,
        reasoning_effort 를 낮게 둬야 추론이 토큰 예산을 잠식해 답변이 잘리는 것을 막는다.
        """
        model = model or settings.openai_model
        token_key = (
            "max_completion_tokens"
            if model.startswith(("gpt-5", "o1", "o3", "o4"))
            else "max_tokens"
        )
        kwargs = {token_key: max_tokens or settings.max_tokens}
        if token_key == "max_completion_tokens" and settings.openai_reasoning_effort:
            kwargs["reasoning_effort"] = settings.openai_reasoning_effort
        return kwargs

    async def complete_json(
        self, system: str, user: str, model: str | None = None, max_tokens: int = 1000
    ) -> str:
        """비스트리밍 단발 완성 — 후속 질문 제안 등 짧은 JSON 응답용 헬퍼.

        model 을 주면 기본 챗 모델 대신 그 모델로 호출한다 (예: gpt-5-mini).
        응답 텍스트(원문)를 그대로 반환하며, JSON 파싱은 호출부 책임이다.
        """
        client = self._client_lazy()
        model = model or settings.openai_model
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **self._completion_kwargs(model=model, max_tokens=max_tokens),
        )
        return (resp.choices[0].message.content or "") if resp.choices else ""

    async def stream_chat(self, system: str, messages: list[dict]) -> AsyncIterator[str]:
        client = self._client_lazy()
        stream = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "system", "content": system}, *messages],
            stream=True,
            **self._completion_kwargs(),
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta

    async def stream_chat_with_tools(
        self, system: str, messages: list[dict], tool_schemas: list[dict]
    ) -> AsyncIterator[dict]:
        """도구 스키마를 붙인 스트리밍 호출 — 에이전트 루프의 저수준 제너레이터.

        yield 하는 이벤트:
        - {"type": "content", "content": str}       : 답변 텍스트 델타 (즉시)
        - {"type": "tool_calls", "tool_calls": [...]}: 스트림 종료 후 1회.
          각 항목은 {"id", "name", "arguments"(JSON 문자열)} — 델타를 인덱스별로 누적한 결과.
        """
        client = self._client_lazy()
        kwargs = self._completion_kwargs()
        if tool_schemas:
            kwargs["tools"] = tool_schemas
            kwargs["tool_choice"] = "auto"
        stream = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "system", "content": system}, *messages],
            stream=True,
            **kwargs,
        )
        # tool_call 델타는 index 기준으로 흩어져 오므로 id/name/arguments 를 누적한다.
        pending: dict[int, dict] = {}
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield {"type": "content", "content": delta.content}
            for tc in delta.tool_calls or []:
                slot = pending.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function.arguments:
                        slot["arguments"] += tc.function.arguments
        if pending:
            yield {
                "type": "tool_calls",
                "tool_calls": [pending[i] for i in sorted(pending)],
            }
