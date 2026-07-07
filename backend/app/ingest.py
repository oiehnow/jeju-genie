"""Ingest 파이프라인 — 등록된 모든 커넥터를 순회해 RAG 인덱스를 (재)구축.

실행:
    python -m app.ingest            # 활성 커넥터 전부
    python -m app.ingest --reset    # 인덱스 비우고 재구축
    python -m app.ingest --push     # 완료 후 GCS 업로드 (배포용)

/api/ingest 엔드포인트에서도 동일 함수를 호출한다.
"""
import argparse
import hashlib
import logging

from app.connectors.base import discover
from app.rag.chunker import chunk_text
from app.rag.store import VectorStore, push_index_to_gcs

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run_ingest(reset: bool = False, push: bool = False) -> dict:
    store = VectorStore()
    if reset:
        store.reset()
        logger.info("인덱스 리셋")

    connectors = discover()
    summary: dict[str, int] = {}
    for name, cls in connectors.items():
        conn = cls()
        if not conn.enabled():
            logger.warning("커넥터 '%s' 비활성 (키/설정 없음) — skip", name)
            summary[name] = -1
            continue
        docs = conn.fetch()
        ids, texts, metas = [], [], []
        seen: set[str] = set()
        for doc in docs:
            for j, chunk in enumerate(chunk_text(doc.text)):
                uid = hashlib.md5(f"{doc.source}:{doc.title}:{j}:{chunk[:64]}".encode()).hexdigest()
                if uid in seen:  # 동일 내용 중복 레코드 skip (일부 API가 같은 데이터 반복 반환)
                    continue
                seen.add(uid)
                ids.append(uid)
                texts.append(chunk)
                metas.append(
                    {"source": doc.source, "title": doc.title, "url": doc.url, "chunk": j}
                )
        if texts:
            # 임베딩 API 배치 제한 대응: 64개 단위
            for i in range(0, len(texts), 64):
                store.add(ids[i : i + 64], texts[i : i + 64], metas[i : i + 64])
        summary[name] = len(texts)
        logger.info("커넥터 '%s': 문서 %d개 → 청크 %d개 적재", name, len(docs), len(texts))

    logger.info("인덱스 총 청크 수: %d", store.count())
    if push:
        push_index_to_gcs()
    return {"connectors": summary, "total_chunks": store.count()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()
    result = run_ingest(reset=args.reset, push=args.push)
    print(result)
