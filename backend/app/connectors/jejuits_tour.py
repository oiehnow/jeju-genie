"""제주교통정보센터 C-ITS 관광지 커넥터 — 관광지 콘텐츠를 RAG에 편입.

JEJUITS_CITS_CODE(코드=REDACTED) 가 .env 에 있으면 활성화된다.
관광지명/주소/소개 등 텍스트 콘텐츠라 RAG 문서로 적합 (약 1,100+건).

API: http://api.jejuits.go.kr/api/infoTourList?code={code}
"""
import httpx

from app.config import settings
from app.connectors.base import BaseConnector, Document, register

API_URL = "http://api.jejuits.go.kr/api/infoTourList"


@register
class JejuItsTourConnector(BaseConnector):
    name = "jejuits_tour"

    def enabled(self) -> bool:
        return bool(settings.jejuits_cits_code)

    def fetch(self) -> list[Document]:
        docs: list[Document] = []
        with httpx.Client(timeout=30) as client:
            r = client.get(API_URL, params={"code": settings.jejuits_cits_code})
            r.raise_for_status()
            data = r.json()
            for it in data.get("info", []):
                title = it.get("title", "")
                parts = [
                    f"# {title}",
                    f"분류: {it.get('contents_label', '')}",
                    f"주소: {it.get('address', '')}",
                    f"소개: {it.get('introduction', '') or it.get('summary', '')}",
                ]
                text = "\n".join(p for p in parts if p.split(": ", 1)[-1])
                if not text.strip("# ").strip():
                    continue
                docs.append(
                    Document(
                        text=text,
                        source="jejuits_tour",
                        title=title,
                        metadata={"contents_id": it.get("contents_id", "")},
                    )
                )
        return docs
