"""시드 문서 커넥터 — data/seed/*.md 를 그대로 문서로 편입.

API 키가 하나도 없어도 플랫폼이 동작하도록 하는 기본 데이터소스.
운영 데이터가 쌓이기 전 데모/스모크 테스트 용도이자,
"파일 드롭 = 지식 추가"라는 가장 단순한 커넥터 예시.
"""
import glob
import os

from app.config import settings
from app.connectors.base import BaseConnector, Document, register


@register
class StaticDocsConnector(BaseConnector):
    name = "static_docs"

    def enabled(self) -> bool:
        return os.path.isdir(settings.seed_docs_dir)

    def fetch(self) -> list[Document]:
        docs = []
        for path in sorted(glob.glob(os.path.join(settings.seed_docs_dir, "*.md"))):
            with open(path, encoding="utf-8") as f:
                text = f.read()
            fname = os.path.basename(path)
            title = text.splitlines()[0].lstrip("# ").strip() if text.strip() else fname
            docs.append(Document(text=text, source=f"seed:{fname}", title=title))
        return docs
