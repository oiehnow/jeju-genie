"""OpenAI(GPT) 프로바이더 — OPENAI_API_KEY가 설정되면 활성화.

키가 없으면 available()=False → factory가 Ollama로 폴백.
"""
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
        stream = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "system", "content": system}, *messages],
            max_tokens=settings.max_tokens,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
