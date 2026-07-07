"""제주 실시간 라이브 도구 — 인덱스에 넣으면 낡는 데이터를 질의 시점에 호출.

LLM 함수호출로 선택된다. 각 도구는 결과를 사람이 읽을 수 있는 짧은 텍스트로 반환.
키는 .env / config 에서 읽으며, 키 없으면 enabled()=False 로 목록에서 빠진다.
"""
import xml.etree.ElementTree as ET

import httpx

from app.config import settings
from app.connectors._extract import load_sources
from app.tools.base import BaseTool, register_tool


def _get(url: str, params: dict | None = None) -> httpx.Response:
    with httpx.Client(timeout=20, verify=False, follow_redirects=True) as c:
        return c.get(url, params=params or {})


@register_tool
class JejuWeatherTool(BaseTool):
    name = "jeju_airport_weather"
    description = "제주공항(ICAO RKPC)의 실시간 항공기상(METAR: 기온/바람/시정/구름/기압)을 조회한다. 제주 현재 날씨/공항 기상 질문에 사용."
    parameters = {"type": "object", "properties": {}}

    def enabled(self) -> bool:
        return bool(settings.kma_apihub_key)

    def run(self, **kwargs) -> str:
        url = "https://apihub.kma.go.kr/api/typ02/openApi/AmmIwxxmService/getMetar"
        r = _get(url, {"icao": "RKPC", "numOfRows": 1, "dataType": "XML",
                       "authKey": settings.kma_apihub_key})
        # IWXXM METAR에서 핵심 관측값(기온/이슬점/풍향/풍속/기압)만 뽑는다.
        want = {
            "airTemperature": "기온", "dewpointTemperature": "이슬점",
            "meanWindDirection": "풍향", "meanWindSpeed": "풍속", "qnh": "기압",
        }
        found: dict[str, str] = {}
        try:
            for el in ET.fromstring(r.content).iter():
                tag = el.tag.rsplit("}", 1)[-1]
                if tag in want and (el.text or "").strip() and want[tag] not in found:
                    uom = el.get("uom", "")
                    found[want[tag]] = f"{el.text.strip()}{uom}"
        except ET.ParseError:
            pass
        if not found:
            return "제주공항 기상 조회 실패 (현재 관측 없음)"
        summary = ", ".join(f"{k} {v}" for k, v in found.items())
        return f"제주공항(RKPC) 실시간 항공기상 — {summary}"


@register_tool
class JejuFuelTool(BaseTool):
    name = "jeju_fuel_price"
    description = "제주도 평균 주유소 유가(휘발유/경유 등)를 오피넷에서 실시간 조회한다. 기름값/주유 질문에 사용."
    parameters = {"type": "object", "properties": {}}

    def enabled(self) -> bool:
        return bool(settings.opinet_api_key)

    def run(self, **kwargs) -> str:
        # 오피넷 시도코드 11 = 제주
        r = _get("https://www.opinet.co.kr/api/avgSidoPrice.do",
                 {"out": "json", "code": settings.opinet_api_key, "sido": "11"})
        try:
            oil = r.json().get("RESULT", {}).get("OIL", [])
        except ValueError:
            oil = []
        if not oil:
            return "제주 유가 조회 실패"
        prod = {"B027": "휘발유", "B034": "고급휘발유", "D047": "경유",
                "C004": "실내등유", "K015": "자동차부탄(LPG)"}
        parts = [
            f"{o.get('PRODNM') or prod.get(o.get('PRODCD'), o.get('PRODCD'))}: {o.get('PRICE')}원/L"
            for o in oil
        ]
        return "제주도 평균 유가 — " + ", ".join(parts)


@register_tool
class JejuTrafficTool(BaseTool):
    name = "jeju_realtime_traffic"
    description = "제주 도로의 실시간 교통정보(구간별 통행속도/혼잡)를 조회한다. 지금 교통/도로 상황 질문에 사용."
    parameters = {"type": "object", "properties": {}}

    def enabled(self) -> bool:
        return bool(settings.jejuits_its_code)

    def run(self, **kwargs) -> str:
        r = _get("http://api.jejuits.go.kr/api/getFrafficInfo",
                 {"code": settings.jejuits_its_code, "type": "L"})
        try:
            data = r.json()
        except ValueError:
            return "제주 교통정보 조회 실패"
        info = data.get("info", [])
        if not info:
            return "제주 실시간 교통정보 없음"
        speeds = [s.get("sped") for s in info if isinstance(s.get("sped"), (int, float))]
        avg = round(sum(speeds) / len(speeds), 1) if speeds else 0
        return f"제주 실시간 교통: 관측 구간 {data.get('info_cnt', len(info))}개, 평균 통행속도 약 {avg}km/h."


@register_tool
class JejuGeocodeTool(BaseTool):
    name = "jeju_place_search"
    description = "제주 장소명/주소로 좌표와 위치 정보를 검색한다(VWorld). 특정 장소의 위치/좌표 질문에 사용."
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "검색할 장소명 또는 주소 (예: 성산일출봉)"}},
        "required": ["query"],
    }

    def enabled(self) -> bool:
        return bool(settings.vworld_api_key)

    def run(self, query: str = "", **kwargs) -> str:
        if not query:
            return "검색어가 필요합니다."
        r = _get("https://api.vworld.kr/req/search",
                 {"service": "search", "request": "search", "version": "2.0",
                  "crs": "EPSG:4326", "query": query, "type": "place",
                  "format": "json", "key": settings.vworld_api_key})
        try:
            items = r.json().get("response", {}).get("result", {}).get("items", [])
        except ValueError:
            items = []
        if not items:
            return f"'{query}' 위치를 찾지 못했습니다."
        it = items[0]
        pt = it.get("point", {})
        return (f"{it.get('title', query)} — 주소: {it.get('address', {}).get('road') or it.get('address', {}).get('parcel', '')}, "
                f"좌표(경도,위도): {pt.get('x')}, {pt.get('y')}")


@register_tool
class JejuDataHubStatTool(BaseTool):
    name = "jeju_statistics"
    description = ("제주 통계/시계열 데이터(버스 승객수, 카드소비, 입도객, 유동인구, 전기차 충전, 농산물 시세, "
                  "일별 기상 등 날짜 기반 수치)를 조회한다. 특정 기간 통계 질문에 사용.")
    parameters = {
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "찾을 통계 데이터셋 키워드 (예: 버스 승객, 입도객, 카드소비)"},
            "start_date": {"type": "string", "description": "시작일 YYYYMMDD"},
            "end_date": {"type": "string", "description": "종료일 YYYYMMDD (미입력 시 start_date와 동일)"},
        },
        "required": ["keyword", "start_date"],
    }

    def enabled(self) -> bool:
        return bool(settings.jejudatahub_project_key)

    def run(self, keyword: str = "", start_date: str = "", end_date: str = "", **kwargs) -> str:
        datasets = load_sources().get("jejudatahub", [])
        match = next((d for d in datasets if keyword and keyword in d.get("name", "")), None)
        if not match:
            return f"'{keyword}' 관련 통계 데이터셋을 찾지 못했습니다."
        url = f"https://open.jejudatahub.net/api/proxy/{match['apicode']}/{settings.jejudatahub_project_key}"
        params = {"number": 20, "page": 1, "startDate": start_date,
                  "endDate": end_date or start_date, "searchDate": start_date}
        r = _get(url, params)
        try:
            rows = r.json().get("data", [])
        except ValueError:
            rows = []
        if not rows:
            return f"'{match['name']}' {start_date} 데이터가 없습니다."
        sample = "; ".join(
            ", ".join(f"{k}:{v}" for k, v in row.items() if v not in (None, "")) for row in rows[:5]
        )
        return f"[{match['name']}] {start_date}~{end_date or start_date} (상위 {min(5, len(rows))}건): {sample}"
