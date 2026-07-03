"""Ollama 프로바이더 — 로컬 개발/GPT 키 도착 전 폴백 (qwen3:14b).

qwen3는 기본적으로 thinking 모드가 켜져 있어 응답이 느려질 수 있으므로
system 프롬프트에 /no_think 지시를 붙여 비활성화한다.
"""
import json
from typing import AsyncIterator

import httpx

from app.config import settings
from app.llm.base import LLMProvider


class OllamaProvider(LLMProvider):
    name = "ollama"

    async def available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{settings.ollama_base_url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False

    async def stream_chat(self, system: str, messages: list[dict]) -> AsyncIterator[str]:
        payload = {
            "model": settings.ollama_model,
            "messages": [{"role": "system", "content": system + "\n/no_think"}, *messages],
            "stream": True,
            "options": {"num_predict": settings.max_tokens},
        }
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST", f"{settings.ollama_base_url}/api/chat", json=payload
            ) as resp:
                resp.raise_for_status()
                in_think = False
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    token = data.get("message", {}).get("content", "")
                    if not token:
                        continue
                    # qwen3 <think> 블록은 사용자에게 내보내지 않음
                    if "<think>" in token:
                        in_think = True
                        continue
                    if "</think>" in token:
                        in_think = False
                        continue
                    if not in_think:
                        yield token
