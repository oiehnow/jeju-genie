"""LLM 프로바이더 추상화.

새 프로바이더 추가 = 이 인터페이스 구현 + factory에 한 줄.
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def stream_chat(self, system: str, messages: list[dict]) -> AsyncIterator[str]:
        """messages: [{"role": "user"|"assistant", "content": str}, ...]
        응답 텍스트를 토큰 단위로 yield."""
        raise NotImplementedError
        yield  # pragma: no cover

    @abstractmethod
    async def available(self) -> bool:
        """프로바이더 사용 가능 여부 (키 존재/서버 살아있음)."""


def get_provider():
    """설정에 따라 프로바이더 선택. OPENAI_API_KEY가 .env에 들어오는 순간 GPT로 전환."""
    from app.config import settings

    if settings.resolved_llm_provider() == "openai":
        from app.llm.openai_provider import OpenAIProvider

        return OpenAIProvider()
    from app.llm.ollama_provider import OllamaProvider

    return OllamaProvider()
