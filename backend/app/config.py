"""제주 지니 설정 — pydantic-settings 기반, 전부 환경변수/.env로 덮어쓰기 가능.

키가 나중에 도착하는 것들(OPENAI_API_KEY, 제주 API 키들)은 전부 Optional:
비어 있으면 해당 기능이 자동으로 폴백/비활성되고, 채우는 순간 활성화된다.
"""
import os
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(BASE_DIR), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM ──────────────────────────────────────────────
    # "auto": OPENAI_API_KEY 있으면 openai, 없으면 ollama
    llm_provider: str = "auto"
    openai_api_key: Optional[str] = None          # ★ 사용자가 나중에 제공
    openai_model: str = "gpt-4o-mini"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:14b"
    max_tokens: int = 1024

    # ── 임베딩 ────────────────────────────────────────────
    # LLM과 독립적으로 선택. auto: OpenAI 키 있으면 openai, 없으면 ollama
    embedding_provider: str = "auto"
    openai_embedding_model: str = "text-embedding-3-small"
    ollama_embedding_model: str = "nomic-embed-text"

    # ── RAG ──────────────────────────────────────────────
    chroma_dir: str = os.path.join(BASE_DIR, "chroma_data")
    retrieval_top_k: int = 4
    chunk_size: int = 700
    chunk_overlap: int = 100

    # ── 커넥터 키들 (★ 사용자가 나중에 제공 — 비면 해당 커넥터 skip) ──
    visitjeju_api_key: Optional[str] = None       # 제주관광공사 Visit Jeju
    data_go_kr_api_key: Optional[str] = None      # 공공데이터포털 공통 키
    jejuits_cits_code: Optional[str] = None       # 제주교통정보센터 C-ITS (관광지/주유소/전기차 등)
    jejuits_its_code: Optional[str] = None        # 제주교통정보센터 ITS (교통시설물/실시간교통)
    jejudatahub_project_key: Optional[str] = None  # 제주데이터허브 projectKey (proxy 호출용)
    opinet_api_key: Optional[str] = None          # 오피넷 유가 (실시간 조회 도구용)
    kma_apihub_key: Optional[str] = None          # 기상청 API허브 (항공기상/낙뢰, 실시간 도구용)
    vworld_api_key: Optional[str] = None          # VWorld 공간정보 (지오코더/검색/지도)
    seed_docs_dir: str = os.path.join(BASE_DIR, "data", "seed")

    # ── 배포/운영 ─────────────────────────────────────────
    gcs_bucket: Optional[str] = None              # 설정 시 시작할 때 Chroma 인덱스 pull
    gcs_chroma_prefix: str = "jeju-genie/chroma"
    port: int = 8080

    def resolved_llm_provider(self) -> str:
        if self.llm_provider != "auto":
            return self.llm_provider
        return "openai" if self.openai_api_key else "ollama"

    def resolved_embedding_provider(self) -> str:
        if self.embedding_provider != "auto":
            return self.embedding_provider
        return "openai" if self.openai_api_key else "ollama"


settings = Settings()
