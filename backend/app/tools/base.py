"""라이브 도구 플러그인 시스템 — 실시간/수치형 API를 LLM 함수호출로 붙인다.

커넥터(connectors/)가 '정적 콘텐츠 → RAG 인덱스'라면,
도구(tools/)는 '실시간 질의 → 그 자리에서 호출'이다.
유가·기상·교통·분양가·좌표처럼 인덱스에 넣으면 낡는 데이터를 담당.

새 도구 추가 3단계:
1. tools/ 에 파일 생성, BaseTool 상속 + @register_tool
2. 필요한 키를 config.py / .env 에 추가
3. openai_schema() 가 자동으로 LLM 함수 목록에 편입됨 (chat 흐름)

tools/ 패키지의 모든 모듈은 discover_tools() 시 자동 import 된다.
"""
import importlib
import pkgutil
from abc import ABC, abstractmethod


class BaseTool(ABC):
    """실시간 데이터 도구 인터페이스."""

    name: str = "base"
    label: str = ""  # UI '실시간 데이터' 배지에 표시할 짧은 한국어 이름 (비면 name 사용)
    description: str = ""
    # OpenAI function-calling parameters 스키마 (JSON Schema)
    parameters: dict = {"type": "object", "properties": {}}

    @abstractmethod
    def enabled(self) -> bool:
        """키/설정 준비 여부. False면 LLM 함수 목록에서 제외."""

    @abstractmethod
    def run(self, **kwargs) -> str:
        """도구 실행 → LLM 컨텍스트에 넣을 텍스트(요약된 결과) 반환."""

    def openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


_TOOL_REGISTRY: dict[str, type[BaseTool]] = {}


def register_tool(cls: type[BaseTool]) -> type[BaseTool]:
    _TOOL_REGISTRY[cls.name] = cls
    return cls


def discover_tools() -> dict[str, type[BaseTool]]:
    """tools 패키지의 모든 모듈을 import 해 레지스트리를 채운 뒤 반환."""
    import app.tools as pkg

    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.name not in ("base", "__init__"):
            importlib.import_module(f"app.tools.{mod.name}")
    return dict(_TOOL_REGISTRY)


def enabled_tools() -> list[BaseTool]:
    """활성화된 도구 인스턴스 목록."""
    return [cls() for cls in discover_tools().values() if cls().enabled()]
