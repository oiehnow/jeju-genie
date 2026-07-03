"""플랫폼 코어 테스트 — 커넥터 레지스트리 / 청커 / API 스모크."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.connectors.base import BaseConnector, Document, discover, register  # noqa: E402
from app.rag.chunker import chunk_text  # noqa: E402


def test_connector_discovery_finds_builtin():
    registry = discover()
    assert "static_docs" in registry
    assert "visitjeju" in registry


def test_register_decorator_adds_new_connector():
    """플랫폼 핵심 보장: 커넥터 클래스 정의만으로 레지스트리에 등록된다."""

    @register
    class DummyConnector(BaseConnector):
        name = "dummy_test"

        def enabled(self) -> bool:
            return True

        def fetch(self) -> list[Document]:
            return [Document(text="dummy", source="dummy_test")]

    registry = discover()
    assert "dummy_test" in registry
    docs = registry["dummy_test"]().fetch()
    assert docs[0].source == "dummy_test"


def test_static_docs_connector_reads_seed():
    registry = discover()
    conn = registry["static_docs"]()
    assert conn.enabled()
    docs = conn.fetch()
    assert len(docs) >= 3
    assert any("성산일출봉" in d.text for d in docs)


def test_chunker_splits_and_overlaps():
    text = "\n\n".join(f"문단 {i} " + "가나다라" * 50 for i in range(5))
    chunks = chunk_text(text, chunk_size=300, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 300 + 51 for c in chunks)


def test_visitjeju_disabled_without_key(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "visitjeju_api_key", None)
    registry = discover()
    assert registry["visitjeju"]().enabled() is False


def test_health_endpoint():
    from app.main import app

    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["llm_provider"] in ("openai", "ollama")


def test_sources_endpoint():
    from app.main import app

    client = TestClient(app)
    r = client.get("/api/sources")
    assert r.status_code == 200
    names = [c["name"] for c in r.json()["connectors"]]
    assert "static_docs" in names
