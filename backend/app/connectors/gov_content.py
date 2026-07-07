"""제주도청(jeju.go.kr) + 서귀포시 공개 API 콘텐츠 커넥터 (키 불필요).

두 소스 모두 '엔드포인트 GET → 목록 파싱 → 텍스트' 패턴이라 하나로 묶는다.
응답이 XML(<jejunetApi>/<response>)이면 XML로, '{'면 JSON으로 자동 분기.
방언사전/민요/역사인물/속담/신화/전시/미술관/음식점/축제 등 텍스트 콘텐츠를 편입.

엔드포인트 목록은 app/data/jeju_sources.json (jejugokr, seogwipo). 키 불필요.
소스당 최대 MAX_PAGES 페이지까지만.
"""
import logging
import xml.etree.ElementTree as ET

import httpx

from app.connectors._extract import NOISE_DATASETS, load_sources, record_to_text
from app.connectors.base import BaseConnector, Document, register

logger = logging.getLogger("jeju-genie.gov")

MAX_RECORDS = 150  # 소스당 상한 (많은 API가 page 파라미터를 무시하고 전체를 한 번에 반환)
_ITEM_TAGS = ("item", "list")


def _xml_records(root: ET.Element) -> list[dict]:
    """반복되는 item/list 노드를 dict 리스트로."""
    nodes = []
    for tag in _ITEM_TAGS:
        nodes = root.findall(f".//{tag}")
        if nodes:
            break
    out = []
    for n in nodes:
        rec = {c.tag: (c.text or "").strip() for c in n if (c.text or "").strip()}
        if rec:
            out.append(rec)
    return out


def _json_records(data) -> list[dict]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("items", "list", "data", "articleList", "menuContentsList", "collections"):
            v = data.get(key)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
        # 한 단계 더 (response.body.items.item 등)
        for v in data.values():
            if isinstance(v, dict):
                got = _json_records(v)
                if got:
                    return got
    return []


@register
class GovContentConnector(BaseConnector):
    name = "gov_content"

    def enabled(self) -> bool:
        return True  # 키 불필요 공개 API

    def fetch(self) -> list[Document]:
        src = load_sources()
        targets = [("jejugokr", s) for s in src.get("jejugokr", [])]
        targets += [("seogwipo", s) for s in src.get("seogwipo", [])]
        docs: list[Document] = []
        with httpx.Client(timeout=30, follow_redirects=True, verify=False) as client:
            for origin, s in targets:
                name, ep = s.get("name", ""), s.get("endpoint", "")
                if not ep or name in NOISE_DATASETS:
                    continue
                got = self._fetch_one(client, ep)
                for rec in got:
                    title, body, meta = record_to_text(rec)
                    if not body.strip("# ").strip():
                        continue
                    meta["dataset"] = name
                    docs.append(
                        Document(text=body, source=f"{origin}:{name}", title=title or name, metadata=meta)
                    )
        logger.info("gov_content: 문서 %d개 (소스 %d개)", len(docs), len(targets))
        return docs

    def _fetch_one(self, client: httpx.Client, ep: str) -> list[dict]:
        # 대부분 page 파라미터를 무시하고 전체를 반환하므로 page=1만 받고 상한만큼 자른다.
        sep = "&" if "?" in ep else "?"
        try:
            r = client.get(f"{ep}{sep}page=1")
            if r.status_code != 200:
                return []
            if r.text.lstrip().startswith("<"):
                got = _xml_records(ET.fromstring(r.content))
            else:
                got = _json_records(r.json())
        except (httpx.HTTPError, ET.ParseError, ValueError):
            return []
        return got[:MAX_RECORDS]
