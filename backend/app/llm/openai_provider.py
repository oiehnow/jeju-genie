"""OpenAI(GPT) 프로바이더 — OPENAI_API_KEY가 설정되면 활성화.

키가 없으면 available()=False → factory가 Ollama로 폴백.
"""
import json
from typing import AsyncIterator

from app.config import settings
from app.llm.base import LLMProvider


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self):
        self._client = None

    def _client_lazy(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        return self._client

    async def available(self) -> bool:
        return bool(settings.openai_api_key)

    async def stream_chat(self, system: str, messages: list[dict]) -> AsyncIterator[str]:
        client = self._client_lazy()
        # gpt-5/o-계열 추론 모델은 max_tokens 대신 max_completion_tokens 를 요구
        model = settings.openai_model
        token_key = (
            "max_completion_tokens"
            if model.startswith(("gpt-5", "o1", "o3", "o4"))
            else "max_tokens"
        )
        kwargs = {token_key: settings.max_tokens}
        # 추론 모델(gpt-5/o-계열)만 reasoning_effort 지원 — 낮게 둬서 추론이
        # 토큰 예산을 잠식해 답변이 잘리는 현상을 막는다.
        if token_key == "max_completion_tokens" and settings.openai_reasoning_effort:
            kwargs["reasoning_effort"] = settings.openai_reasoning_effort
        stream = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, *messages],
            stream=True,
            **kwargs,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta

    async def decide_tool_calls(
        self, message: str, tool_schemas: list[dict]
    ) -> list[tuple[str, dict]]:
        if not tool_schemas:
            return []
        client = self._client_lazy()
        resp = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": "사용자의 제주 관련 질문에 실시간 데이터(유가/기상/교통/"
                    "분양가/좌표 등)가 필요하면 해당 함수를 호출하라. 필요 없으면 호출하지 마라.",
                },
                {"role": "user", "content": message},
            ],
            tools=tool_schemas,
            tool_choice="auto",
        )
        calls = resp.choices[0].message.tool_calls or []
        out: list[tuple[str, dict]] = []
        for c in calls:
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            out.append((c.function.name, args))
        return out
