"""임베딩 추상화 — OpenAI(text-embedding-3-small) / Ollama(nomic-embed-text).

임베딩 모델이 다르면 벡터 공간이 달라 검색이 깨지므로,
store.py 가 컬렉션 이름에 임베딩 식별자를 포함시켜 인덱스를 분리한다.
"""
import httpx

from app.config import settings


class Embedder:
    def __init__(self):
        self.provider = settings.resolved_embedding_provider()
        self.model = (
            settings.openai_embedding_model
            if self.provider == "openai"
            else settings.ollama_embedding_model
        )

    @property
    def collection_suffix(self) -> str:
        """컬렉션 이름에 붙일 임베딩 식별자 (모델 혼합 방지)."""
        return f"{self.provider}-{self.model}".replace(":", "_").replace("/", "_")

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.provider == "openai":
            return self._embed_openai(texts)
        return self._embed_ollama(texts)

    def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        resp = client.embeddings.create(model=self.model, input=texts)
        return [d.embedding for d in resp.data]

    def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        out = []
        with httpx.Client(timeout=120) as client:
            for text in texts:
                r = client.post(
                    f"{settings.ollama_base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                )
                r.raise_for_status()
                out.append(r.json()["embedding"])
        return out
