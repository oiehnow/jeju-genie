"""제주 공공 API의 다양한 JSON 레코드를 RAG 문서 텍스트로 변환하는 공통 유틸.

소스마다 필드명이 조금씩 달라(placeName/companyName/title …) 하드코딩 대신
우선순위 후보 리스트로 제목/주소/좌표를 자동 추출하고, 나머지 문자열 필드를
'키: 값'으로 이어 본문을 만든다.
"""
import json
import os

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

TITLE_KEYS = [
    "placeName", "companyName", "libraryName", "stationName", "centerName",
    "villageName", "courseName", "chargingPlace", "resto_nm", "recycle_title",
    "title", "name",
]
ADDR_KEYS = ["address", "addressDoro", "addressJibun", "stationAddress", "roadaddress"]
LAT_KEYS = ["latitude", "lat", "gis_y_coor"]
LON_KEYS = ["longitude", "lon", "lng", "gis_x_coor"]
_SKIP = {"photoid", "imgpath", "thumbnailpath", "cover", "coverThumb", "repPhoto"}


def _first(rec: dict, keys: list[str]) -> str:
    for k in keys:
        v = rec.get(k)
        if v not in (None, "", "null"):
            return str(v).strip()
    return ""


def record_to_text(rec: dict) -> tuple[str, str, dict]:
    """레코드 → (title, body_text, metadata). 텍스트 가치 없으면 title="" 반환."""
    if not isinstance(rec, dict):
        return "", "", {}
    title = _first(rec, TITLE_KEYS)
    lines = []
    for k, v in rec.items():
        if k in _SKIP or v in (None, "", "null"):
            continue
        if isinstance(v, (dict, list)):
            v = _first(v, ["label", "value"]) if isinstance(v, dict) else ""
            if not v:
                continue
        sval = str(v).strip()
        if sval and len(sval) < 300:
            lines.append(f"{k}: {sval}")
    meta = {}
    lat, lon = _first(rec, LAT_KEYS), _first(rec, LON_KEYS)
    if lat and lon:
        meta["lat"], meta["lon"] = lat, lon
    body = (f"# {title}\n" if title else "") + "\n".join(lines)
    return title, body, meta


def load_sources() -> dict:
    with open(os.path.join(_DATA, "jeju_sources.json"), encoding="utf-8") as f:
        return json.load(f)
