"""제주 지니 FastAPI 백엔드.

엔드포인트:
- POST /api/chat        : 에이전트 챗 (SSE 스트리밍: status/live/token/map/sources/done 이벤트)
- GET  /api/now         : 헤더 기온 칩 (제주공항 METAR 기온, 10분 캐시)
- GET  /api/live/summary: 사이드바 실시간 패널 (날씨/유가/교통 병렬 조회, 5분 캐시)
- POST /api/suggest     : 문답 기반 후속 질문 3개 제안 (경량 LLM)
- POST /api/ingest      : 인덱스 (재)구축
- GET  /api/sources     : 등록된 커넥터와 활성 상태 (플랫폼 대시보드용)
- GET  /api/health      : 헬스체크 (LLM 프로바이더/인덱스 상태 포함)
- /                     : 프론트엔드 정적 서빙 (frontend/dist 빌드 결과)
"""
import asyncio
import json
import logging
import os
import re
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agent import run_agent
from app.config import settings
from app.connectors.base import discover
from app.llm.base import get_provider
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

        # 에이전트 루프가 dict 이벤트를 yield 하면 여기서는 SSE 직렬화만 담당한다.
        async for event in run_agent(provider, req.message, req.history[-10:], store()):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── 실시간 패널용 간단 인메모리 캐시 (모듈 전역, TTL은 엔드포인트별) ──
_live_cache: dict[str, tuple[float, object]] = {}


def _cache_get(key: str, ttl: float):
    ent = _live_cache.get(key)
    if ent is not None and time.monotonic() - ent[0] < ttl:
        return ent[1]
    return None


def _cache_set(key: str, value):
    _live_cache[key] = (time.monotonic(), value)


@app.get("/api/now")
async def now():
    """헤더 기온 칩 — 제주공항 METAR에서 기온 숫자만 뽑아 반환 (10분 캐시)."""
    cached = _cache_get("now", 600)
    if cached is not None:
        return cached
    from app.tools.jeju_live import JejuWeatherTool

    tool = JejuWeatherTool()
    if not tool.enabled():
        return {"temp": None}
    try:
        text = await tool.run()
    except Exception:
        logger.exception("/api/now 기상 조회 실패")
        return {"temp": None}
    m = re.search(r"기온\s*(-?\d+(?:\.\d+)?)", text or "")
    if not m:
        return {"temp": None}
    result = {"temp": m.group(1), "summary": text}
    _cache_set("now", result)
    return result


@app.get("/api/live/summary")
async def live_summary():
    """사이드바 실시간 패널 — 날씨/유가/교통을 병렬 조회해 요약 (5분 캐시)."""
    cached = _cache_get("live_summary", 300)
    if cached is not None:
        return cached
    from app.tools.jeju_live import JejuFuelTool, JejuTrafficTool, JejuWeatherTool

    tools = [t for t in (JejuWeatherTool(), JejuFuelTool(), JejuTrafficTool()) if t.enabled()]
    results = await asyncio.gather(*(t.run() for t in tools), return_exceptions=True)
    items = []
    for tool, res in zip(tools, results):
        # 예외/빈 결과뿐 아니라 도구가 돌려주는 실패 문구도 패널에서 제외한다.
        if isinstance(res, BaseException) or not res or "조회 실패" in res:
            continue
        items.append({"label": tool.label or tool.name, "theme": tool.theme, "text": res})
    result = {"items": items}
    if items:  # 전부 실패한 응답은 캐시하지 않고 다음 요청에서 재시도
        _cache_set("live_summary", result)
    return result


class SuggestRequest(BaseModel):
    question: str
    answer: str = ""


_SUGGEST_SYSTEM = (
    "너는 제주 여행 도우미다. 사용자와 방금 나눈 문답을 보고, "
    "사용자가 이어서 물을 법한 짧은 제주 관련 후속 질문 3개를 만들어라. "
    "각 질문은 20자 내외의 한국어 문장이며 이모지는 쓰지 않는다. "
    "다른 설명 없이 JSON 배열로만 답하라. 예: [\"질문1\", \"질문2\", \"질문3\"]"
)


@app.post("/api/suggest")
async def suggest(req: SuggestRequest):
    """문답 기반 후속 질문 3개 제안 — 실패/LLM 미가용 시 빈 배열 (500 금지)."""
    provider = get_provider()
    complete = getattr(provider, "complete_json", None)
    if complete is None:
        return {"suggestions": []}
    try:
        if not await provider.available():
            return {"suggestions": []}
        user = f"질문: {req.question}\n답변: {req.answer}"
        raw = await complete(_SUGGEST_SYSTEM, user, model=settings.openai_suggest_model)
        # 모델이 코드펜스 등을 붙여도 JSON 배열 부분만 잘라 파싱한다.
        m = re.search(r"\[.*\]", raw or "", re.DOTALL)
        parsed = json.loads(m.group(0)) if m else []
        suggestions = [s.strip() for s in parsed if isinstance(s, str) and s.strip()][:3]
        return {"suggestions": suggestions}
    except Exception:
        logger.exception("/api/suggest 생성 실패")
        return {"suggestions": []}


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
