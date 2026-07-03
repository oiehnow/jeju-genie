"""제주 지니 FastAPI 백엔드.

엔드포인트:
- POST /api/chat        : RAG 챗 (SSE 스트리밍: token 이벤트 → sources 이벤트 → done)
- POST /api/ingest      : 인덱스 (재)구축
- GET  /api/sources     : 등록된 커넥터와 활성 상태 (플랫폼 대시보드용)
- GET  /api/health      : 헬스체크 (LLM 프로바이더/인덱스 상태 포함)
- /                     : 프론트엔드 정적 서빙 (frontend/dist 빌드 결과)
"""
import json
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import settings
from app.connectors.base import discover
from app.llm.base import get_provider
from app.prompts import build_system_prompt
from app.rag.store import VectorStore, pull_index_from_gcs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jeju-genie")

app = FastAPI(title="제주 지니", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

_store: VectorStore | None = None


def store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store


@app.on_event("startup")
async def startup():
    pulled = pull_index_from_gcs()
    logger.info(
        "startup: llm=%s embed=%s gcs_pull=%s chunks=%d",
        settings.resolved_llm_provider(),
        settings.resolved_embedding_provider(),
        pulled,
        store().count(),
    )


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []  # [{"role": "user"|"assistant", "content": str}]


@app.post("/api/chat")
async def chat(req: ChatRequest):
    provider = get_provider()

    async def event_stream():
        if not await provider.available():
            msg = (
                "지니가 아직 준비 중이에요. LLM 연결이 없습니다 — "
                "OPENAI_API_KEY를 설정하거나 로컬 Ollama를 실행해 주세요."
            )
            yield f"data: {json.dumps({'type': 'token', 'content': msg}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        hits = store().query(req.message)
        system = build_system_prompt(hits)
        messages = [*req.history[-6:], {"role": "user", "content": req.message}]

        try:
            async for token in provider.stream_chat(system, messages):
                yield f"data: {json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("LLM stream error")
            err = f"앗, 지니가 잠깐 말을 잃었어요… ({type(e).__name__})"
            yield f"data: {json.dumps({'type': 'token', 'content': err}, ensure_ascii=False)}\n\n"

        sources = [
            {
                "title": h["metadata"].get("title", ""),
                "source": h["metadata"].get("source", ""),
                "url": h["metadata"].get("url", ""),
            }
            for h in hits
        ]
        # 중복 출처 제거 (순서 유지)
        seen, uniq = set(), []
        for s in sources:
            key = (s["title"], s["source"])
            if key not in seen:
                seen.add(key)
                uniq.append(s)
        yield f"data: {json.dumps({'type': 'sources', 'sources': uniq}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/ingest")
async def ingest(reset: bool = False, push: bool = False):
    from app.ingest import run_ingest

    global _store
    result = run_ingest(reset=reset, push=push)
    _store = None  # 재적재 후 컬렉션 카운트 갱신
    return result


@app.get("/api/sources")
async def sources():
    out = []
    for name, cls in discover().items():
        conn = cls()
        out.append({"name": name, "enabled": conn.enabled()})
    return {"connectors": out, "total_chunks": store().count()}


@app.get("/api/health")
async def health():
    provider = get_provider()
    return {
        "status": "ok",
        "llm_provider": provider.name,
        "llm_available": await provider.available(),
        "embedding_provider": settings.resolved_embedding_provider(),
        "index_chunks": store().count(),
    }


# 프론트엔드 정적 서빙 (도커 이미지에서 frontend/dist 가 여기로 복사됨)
_static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
if os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
