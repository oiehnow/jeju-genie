"""ChromaDB persistent 벡터 스토어 + GCS 동기화 (Cloud Run 스테이트리스 대응)."""
import logging
import os

import chromadb

from app.config import settings
from app.rag.embedder import Embedder

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self, embedder: Embedder | None = None):
        self.embedder = embedder or Embedder()
        self._client = chromadb.PersistentClient(path=settings.chroma_dir)
        self.collection = self._client.get_or_create_collection(
            name=f"jeju-{self.embedder.collection_suffix}",
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, ids: list[str], texts: list[str], metadatas: list[dict]) -> None:
        embeddings = self.embedder.embed(texts)
        self.collection.upsert(ids=ids, documents=texts, embeddings=embeddings, metadatas=metadatas)

    def query(self, text: str, top_k: int | None = None) -> list[dict]:
        top_k = top_k or settings.retrieval_top_k
        if self.collection.count() == 0:
            return []
        embedding = self.embedder.embed([text])[0]
        res = self.collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k, self.collection.count()),
        )
        hits = []
        for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
            hits.append({"text": doc, "metadata": meta or {}, "distance": dist})
        return hits

    def count(self) -> int:
        return self.collection.count()

    def reset(self) -> None:
        name = self.collection.name
        self._client.delete_collection(name)
        self.collection = self._client.get_or_create_collection(
            name=name, metadata={"hnsw:space": "cosine"}
        )


# ── GCS 동기화 (settings.gcs_bucket 설정 시에만) ──────────────────────────

def pull_index_from_gcs() -> bool:
    """시작 시 GCS에 저장된 Chroma 디렉터리를 내려받는다. 성공 시 True."""
    if not settings.gcs_bucket:
        return False
    try:
        from google.cloud import storage

        client = storage.Client()
        blobs = list(client.list_blobs(settings.gcs_bucket, prefix=settings.gcs_chroma_prefix))
        if not blobs:
            logger.info("GCS에 Chroma 인덱스 없음 (%s)", settings.gcs_chroma_prefix)
            return False
        for blob in blobs:
            rel = blob.name[len(settings.gcs_chroma_prefix) :].lstrip("/")
            dest = os.path.join(settings.chroma_dir, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            blob.download_to_filename(dest)
        logger.info("GCS에서 Chroma 인덱스 %d개 파일 pull 완료", len(blobs))
        return True
    except Exception as e:  # 배포 초기에 권한/네트워크로 실패해도 앱은 떠야 함
        logger.warning("GCS 인덱스 pull 실패: %s", e)
        return False


def push_index_to_gcs() -> int:
    """ingest 후 Chroma 디렉터리를 GCS로 올린다. 업로드 파일 수 반환."""
    if not settings.gcs_bucket:
        return 0
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(settings.gcs_bucket)
    n = 0
    for root, _dirs, files in os.walk(settings.chroma_dir):
        for fname in files:
            path = os.path.join(root, fname)
            rel = os.path.relpath(path, settings.chroma_dir).replace("\\", "/")
            bucket.blob(f"{settings.gcs_chroma_prefix}/{rel}").upload_from_filename(path)
            n += 1
    logger.info("Chroma 인덱스 %d개 파일 GCS push 완료", n)
    return n
