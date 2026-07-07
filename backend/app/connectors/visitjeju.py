"""제주관광공사 Visit Jeju API 커넥터 (스텁 준비 완료 — 키만 넣으면 동작).

사용자가 api.visitjeju.net 키를 받아 .env 의 VISITJEJU_API_KEY 에 넣으면
enabled() 가 True 가 되어 ingest 에 자동 편입된다.

API 문서: https://api.visitjeju.net (관광지/음식점/숙박 콘텐츠 목록)
"""
import httpx

from app.config import settings
from app.connectors.base import BaseConnector, Document, register

API_URL = "https://api.visitjeju.net/vsjApi/contents/searchList"
MAX_PAGES = 6  # 초기 인덱스 크기 상한 (페이지당 100건)


@register
class VisitJejuConnector(BaseConnector):
    name = "visitjeju"

    def enabled(self) -> bool:
        return bool(settings.visitjeju_api_key)

    def fetch(self) -> list[Document]:
        docs: list[Document] = []
        page = 1
        with httpx.Client(timeout=30) as client:
            while True:
                r = client.get(
                    API_URL,
                    params={
                        "apiKey": settings.visitjeju_api_key,
                        "locale": "kr",
                        "page": page,
                    },
                )
                r.raise_for_status()
                data = r.json()
                items = data.get("items", [])
                if not items:
                    break
                for it in items:
                    title = it.get("title", "")
                    parts = [
                        f"# {title}",
                        f"분류: {it.get('contentscd', {}).get('label', '')}",
                        f"주소: {it.get('address', '')}",
                        f"소개: {it.get('introduction', '')}",
                        f"태그: {it.get('alltag', '')}",
                    ]
                    docs.append(
                        Document(
                            text="\n".join(p for p in parts if p.split(": ", 1)[-1]),
                            source="visitjeju",
                            title=title,
                            url=f"https://www.visitjeju.net/kr/detail/view?contentsid={it.get('contentsid', '')}",
                            metadata={"contentsid": it.get("contentsid", "")},
                        )
                    )
                if page >= min(int(data.get("pageCount", 1)), MAX_PAGES):
                    break
                page += 1
        return docs
