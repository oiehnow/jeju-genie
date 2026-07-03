"""커넥터 플러그인 시스템 — 제주 지니 플랫폼의 핵심.

새 데이터소스 추가 3단계:
1. connectors/ 에 파일 생성, BaseConnector 상속 + @register 데코레이터
2. 필요한 API 키를 config.py 와 .env 에 추가
3. `python -m app.ingest` 실행 → 자동으로 RAG 인덱스에 편입

connectors/ 패키지의 모든 모듈은 앱 시작 시 자동 import 되므로
파일을 만들기만 하면 레지스트리에 올라간다.
"""
import importlib
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Document:
    """커넥터가 반환하는 문서 단위. text가 청킹→임베딩→검색 대상."""

    text: str
    source: str                      # 출처 표시용 (예: "visitjeju", "seed:성산일출봉.md")
    title: str = ""
    url: str = ""
    metadata: dict = field(default_factory=dict)


class BaseConnector(ABC):
    """모든 데이터소스 커넥터의 인터페이스."""

    name: str = "base"

    @abstractmethod
    def enabled(self) -> bool:
        """키/설정이 준비됐는지. False면 ingest에서 조용히 skip (경고 로그만)."""

    @abstractmethod
    def fetch(self) -> list[Document]:
        """데이터소스에서 문서를 수집해 반환."""


_REGISTRY: dict[str, type[BaseConnector]] = {}


def register(cls: type[BaseConnector]) -> type[BaseConnector]:
    """@register 데코레이터 — 클래스 정의만으로 플랫폼에 등록."""
    _REGISTRY[cls.name] = cls
    return cls


def discover() -> dict[str, type[BaseConnector]]:
    """connectors 패키지의 모든 모듈을 import 해 레지스트리를 채운 뒤 반환."""
    import app.connectors as pkg

    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.name not in ("base", "__init__"):
            importlib.import_module(f"app.connectors.{mod.name}")
    return dict(_REGISTRY)
