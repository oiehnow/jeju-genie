"""제주데이터허브 제네릭 커넥터 — 93개 데이터셋을 하나의 커넥터로 편입.

모든 데이터셋이 동일 규격: open.jejudatahub.net/api/proxy/{apicode}/{projectKey}
- 날짜 파라미터 없이 200 OK → 시설/장소 마스터(콘텐츠형) → RAG 인덱스 편입
- 400 (startDate/searchDate 필요) → 통계/시계열형 → 인덱스 skip (tools/jejudatahub_stat 담당)

apicode 목록은 app/data/jeju_sources.json 에 번들(이미지에 포함). projectKey는 .env.
데이터셋당 최대 MAX_RECORDS건까지만 인덱싱(임베딩 비용/시간 상한).
"""
import logging

import httpx

from app.config import settings
from app.connectors._extract import load_sources, record_to_text
from app.connectors.base import BaseConnector, Document, register

logger = logging.getLogger("jeju-genie.datahub")

PROXY = "https://open.jejudatahub.net/api/proxy"
MAX_RECORDS = 200  # 데이터셋당 상한


@register
class JejuDataHubConnector(BaseConnector):
    name = "jejudatahub"

    def enabled(self) -> bool:
        return bool(settings.jejudatahub_project_key)

    def fetch(self) -> list[Document]:
        pkey = settings.jejudatahub_project_key
        datasets = load_sources().get("jejudatahub", [])
        docs: list[Document] = []
        content_n = stat_n = 0
        with httpx.Client(timeout=30) as client:
            for ds in datasets:
                code, name = ds.get("apicode"), ds.get("name", "")
                if not code:
                    continue
                url = f"{PROXY}/{code}/{pkey}"
                try:
                    r = client.get(url, params={"number": MAX_RECORDS, "page": 1})
                except httpx.HTTPError:
                    continue
                if r.status_code != 200:
                    stat_n += 1  # 날짜 필요(통계형) → 라이브 도구가 담당
                    continue
                try:
                    rows = r.json().get("data", [])
                except ValueError:
                    continue
                if not rows:
                    continue
                content_n += 1
                for rec in rows:
                    title, body, meta = record_to_text(rec)
                    if not body.strip("# ").strip():
                        continue
                    meta["dataset"] = name
                    docs.append(
                        Document(text=body, source=f"datahub:{name}", title=title or name, metadata=meta)
                    )
        logger.info("datahub: 콘텐츠 %d셋 → 문서 %d개 (통계형 %d셋 skip)", content_n, len(docs), stat_n)
        return docs
