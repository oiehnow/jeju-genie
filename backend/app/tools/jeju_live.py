"""제주 실시간 라이브 도구 — 인덱스에 넣으면 낡는 데이터를 질의 시점에 호출.

LLM 함수호출로 선택된다. 각 도구는 결과를 사람이 읽을 수 있는 짧은 텍스트로 반환.
키는 .env / config 에서 읽으며, 키 없으면 enabled()=False 로 목록에서 빠진다.
에이전트가 asyncio.gather 로 병렬 실행하므로 run 은 전부 async (base.BaseTool 규약).
"""
import xml.etree.ElementTree as ET
from urllib.parse import quote

import httpx

from app.config import settings
from app.connectors._extract import load_sources
from app.tools.base import BaseTool, register_tool

# 일부 공공 서버(jeju.go.kr 등)가 기본 python UA 요청을 리셋하므로 브라우저 UA를 붙인다.
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


async def _get(url: str, params: dict | None = None) -> httpx.Response:
    async with httpx.AsyncClient(timeout=20, verify=False,
                                 follow_redirects=True, headers=_UA) as c:
        return await c.get(url, params=params or {})


@register_tool
class JejuWeatherTool(BaseTool):
    name = "jeju_airport_weather"
    label = "제주공항 날씨"
    theme = "weather"
    description = "제주공항(ICAO RKPC)의 실시간 항공기상(METAR: 기온/바람/시정/구름/기압)을 조회한다. 제주 현재 날씨/공항 기상 질문에 사용."
    parameters = {"type": "object", "properties": {}}

    def enabled(self) -> bool:
        return bool(settings.kma_apihub_key)

    async def run(self, **kwargs) -> str:
        url = "https://apihub.kma.go.kr/api/typ02/openApi/AmmIwxxmService/getMetar"
        try:
            r = await _get(url, {"icao": "RKPC", "numOfRows": 1, "dataType": "XML",
                                 "authKey": settings.kma_apihub_key})
        except httpx.HTTPError:
            return "제주공항 기상 조회 실패 (네트워크 오류)"
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
    label = "제주 유가"
    theme = "fuel"
    description = "제주도 평균 주유소 유가(휘발유/경유 등)를 오피넷에서 실시간 조회한다. 기름값 시세/평균 유가 질문에 사용. 개별 주유소는 jeju_gas_station 사용."
    parameters = {"type": "object", "properties": {}}

    def enabled(self) -> bool:
        return bool(settings.opinet_api_key)

    async def run(self, **kwargs) -> str:
        # 오피넷 시도코드 11 = 제주
        try:
            r = await _get("https://www.opinet.co.kr/api/avgSidoPrice.do",
                           {"out": "json", "code": settings.opinet_api_key, "sido": "11"})
        except httpx.HTTPError:
            return "제주 유가 조회 실패 (네트워크 오류)"
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
    label = "제주 실시간 교통"
    theme = "traffic"
    description = "제주 도로의 실시간 교통정보(구간별 통행속도/혼잡)를 조회한다. 지금 교통/도로 상황 질문에 사용."
    parameters = {"type": "object", "properties": {}}

    def enabled(self) -> bool:
        return bool(settings.jejuits_its_code)

    async def run(self, **kwargs) -> str:
        try:
            r = await _get("http://api.jejuits.go.kr/api/getFrafficInfo",
                           {"code": settings.jejuits_its_code, "type": "L"})
        except httpx.HTTPError:
            return "제주 교통정보 조회 실패 (네트워크 오류)"
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
    label = "제주 장소검색"
    theme = "place"
    description = "제주 장소명/주소로 좌표와 위치 정보를 검색한다(VWorld). 특정 장소의 위치/좌표 질문에 사용."
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "검색할 장소명 또는 주소 (예: 성산일출봉)"}},
        "required": ["query"],
    }

    # VWorld 는 '서귀포 찜질방'처럼 지역명이 붙은 조합 질의를 자주 NOT_FOUND 로
    # 처리한다 (2026-07 실측: '탐라사우나' OK, '서귀포 찜질방' NOT_FOUND) —
    # 못 찾으면 지역어를 떼고 한 번 더 시도한다.
    _REGION_WORDS = ("제주특별자치도", "제주도", "제주시", "서귀포시", "서귀포", "제주")

    def enabled(self) -> bool:
        return bool(settings.vworld_api_key)

    async def _search(self, query: str) -> list[dict]:
        try:
            r = await _get("https://api.vworld.kr/req/search",
                           {"service": "search", "request": "search", "version": "2.0",
                            "crs": "EPSG:4326", "query": query, "type": "place",
                            "format": "json", "key": settings.vworld_api_key})
            result = r.json().get("response", {}).get("result", {})
        except (httpx.HTTPError, ValueError):
            return []
        return result.get("items", []) if isinstance(result, dict) else []

    async def run(self, query: str = "", **kwargs) -> str:
        if not query:
            return "검색어가 필요합니다."
        items = await self._search(query)
        if not items:
            stripped = query
            for w in self._REGION_WORDS:
                stripped = stripped.replace(w, " ")
            stripped = " ".join(stripped.split())
            if stripped and stripped != query:
                items = await self._search(stripped)
        if not items:
            return f"'{query}' 위치를 찾지 못했습니다."
        it = items[0]
        pt = it.get("point", {})
        title = it.get("title", query)
        # 지도 마커 + 네이버 지도 출처 칩 (VWorld point 는 x=경도, y=위도 문자열)
        try:
            self.map_points.append({"name": title,
                                    "lat": float(pt.get("y")), "lng": float(pt.get("x"))})
        except (TypeError, ValueError):
            pass
        self.refs.append({"title": f"네이버 지도: {title}",
                          "url": f"https://map.naver.com/p/search/{quote(title)}"})
        return (f"{title} — 주소: {it.get('address', {}).get('road') or it.get('address', {}).get('parcel', '')}, "
                f"좌표(경도,위도): {pt.get('x')}, {pt.get('y')}")


@register_tool
class JejuDataHubStatTool(BaseTool):
    name = "jeju_statistics"
    label = "제주 통계"
    theme = "stats"
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

    async def run(self, keyword: str = "", start_date: str = "", end_date: str = "", **kwargs) -> str:
        datasets = load_sources().get("jejudatahub", [])
        match = next((d for d in datasets if keyword and keyword in d.get("name", "")), None)
        if not match:
            return f"'{keyword}' 관련 통계 데이터셋을 찾지 못했습니다."
        url = f"https://open.jejudatahub.net/api/proxy/{match['apicode']}/{settings.jejudatahub_project_key}"
        params = {"number": 20, "page": 1, "startDate": start_date,
                  "endDate": end_date or start_date, "searchDate": start_date}
        try:
            r = await _get(url, params)
        except httpx.HTTPError:
            return f"'{match['name']}' 통계 조회 실패 (네트워크 오류)"
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


@register_tool
class JejuEvChargerTool(BaseTool):
    name = "jeju_ev_charger"
    label = "제주 전기차 충전소"
    theme = "ev"
    description = ("제주 전기차 충전소를 조회한다. 지역/장소 키워드(region)를 주면 해당 지역 충전소 목록"
                   "(급속/완속 충전기 수, 운영시간)을, 없으면 제주 전역 충전기 실시간 집계를 요약한다. "
                   "전기차 충전 어디서 하나/충전소 있나 질문에 사용.")
    parameters = {
        "type": "object",
        "properties": {
            "region": {"type": "string", "description": "충전소를 찾을 장소/지역 키워드 (예: 성산, 공항, 중문). 비우면 제주 전역 집계"},
            "limit": {"type": "integer", "description": "목록 최대 건수 (기본 5)"},
        },
    }

    def enabled(self) -> bool:
        # C-ITS(전역 집계) 또는 데이터허브(장소 검색) 둘 중 하나만 있어도 동작
        return bool(settings.jejuits_cits_code or settings.jejudatahub_project_key)

    async def _region_list(self, region: str, limit: int) -> str:
        """데이터허브 '전기자동차 충전소 정보'에서 장소 키워드로 검색."""
        dataset = next((d for d in load_sources().get("jejudatahub", [])
                        if d.get("name") == "전기자동차 충전소 정보"), None)
        if not dataset:
            return ""
        url = f"https://open.jejudatahub.net/api/proxy/{dataset['apicode']}/{settings.jejudatahub_project_key}"
        # 주의: 이 프록시는 필터(chargingPlace)와 number/page를 함께 주면 빈 data를 반환한다.
        r = await _get(url, {"chargingPlace": region})
        try:
            body = r.json()
        except ValueError:
            return ""
        rows = body.get("data", [])
        if not rows:
            return ""
        parts = []
        for row in rows[:limit]:
            fast = row.get("quickChargerCount") or 0
            slow = row.get("chargerCount") or 0
            hours = f"{row.get('startTime', '?')}~{row.get('endTime', '?')}"
            name = row.get("chargingPlace", "이름미상")
            parts.append(f"{name}(급속{fast}·완속{slow}, {hours})")
            # 데이터허브 충전소 행에 latitude/longitude 가 있음 (실측 확인) — 지도 마커 적재
            lat, lng = row.get("latitude"), row.get("longitude")
            if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
                self.map_points.append({"name": name, "lat": float(lat), "lng": float(lng)})
        tot = body.get("totCnt", len(rows))
        return f"'{region}' 충전소 {tot}곳 중 {len(parts)}곳 — " + "; ".join(parts)

    async def _island_summary(self) -> str:
        """C-ITS infoEvList — 충전소별 급속/완속 현황의 전역 집계."""
        r = await _get("http://api.jejuits.go.kr/api/infoEvList",
                       {"code": settings.jejuits_cits_code})
        try:
            data = r.json()
        except ValueError:
            return ""
        info = data.get("info", [])
        if not info:
            return ""
        fast = sum(s.get("fast") or 0 for s in info)
        slow = sum(s.get("slow") or 0 for s in info)
        return (f"제주 전역 충전소 {data.get('info_cnt', len(info))}곳 — "
                f"급속 {fast}기, 완속 {slow}기 (C-ITS 실시간 집계)")

    async def run(self, region: str = "", limit: int = 5, **kwargs) -> str:
        try:
            limit = max(1, min(int(limit or 5), 10))
        except (TypeError, ValueError):
            limit = 5
        try:
            if region and settings.jejudatahub_project_key:
                found = await self._region_list(region, limit)
                if found:
                    return found
                # 지역 검색 결과가 없으면 전역 집계로 폴백
            if settings.jejuits_cits_code:
                summary = await self._island_summary()
                if summary:
                    prefix = f"'{region}' 지역 충전소를 찾지 못했습니다. " if region else ""
                    return prefix + summary
        except httpx.HTTPError:
            return "제주 전기차 충전소 조회 실패 (네트워크 오류)"
        return "제주 전기차 충전소 조회 실패"


@register_tool
class JejuGasStationTool(BaseTool):
    name = "jeju_gas_station"
    label = "제주 주유소 가격"
    theme = "fuel"
    description = ("제주시/서귀포시의 최저가 주유소 상위 목록(상호/가격/주소)을 오피넷에서 실시간 조회한다. "
                   "싼 주유소 어디/특정 지역 기름값 질문에 사용. 도 평균 시세는 jeju_fuel_price 사용.")
    parameters = {
        "type": "object",
        "properties": {
            "region": {"type": "string", "enum": ["제주시", "서귀포시"],
                       "description": "조회 지역 (기본 제주시)"},
            "fuel": {"type": "string", "enum": ["휘발유", "고급휘발유", "경유", "LPG"],
                     "description": "유종 (기본 휘발유)"},
        },
    }
    # 오피넷 areaCode.do(시도 11=제주) 조회 결과: 1101=제주시, 1102=서귀포시
    _AREA = {"제주시": "1101", "서귀포시": "1102"}
    _PROD = {"휘발유": "B027", "고급휘발유": "B034", "경유": "D047", "LPG": "K015"}

    def enabled(self) -> bool:
        return bool(settings.opinet_api_key)

    async def run(self, region: str = "제주시", fuel: str = "휘발유", **kwargs) -> str:
        area = self._AREA.get(region, "1101")
        prodcd = self._PROD.get(fuel, "B027")
        try:
            r = await _get("https://www.opinet.co.kr/api/lowTop10.do",
                           {"out": "json", "code": settings.opinet_api_key,
                            "prodcd": prodcd, "area": area, "cnt": 7})
        except httpx.HTTPError:
            return f"{region} 주유소 가격 조회 실패 (네트워크 오류)"
        try:
            rows = r.json().get("RESULT", {}).get("OIL", [])
        except ValueError:
            rows = []
        if not rows:
            return f"{region} {fuel} 최저가 주유소 조회 실패"
        parts = [
            f"{o.get('OS_NM', '이름미상')} {o.get('PRICE')}원/L ({o.get('NEW_ADR') or o.get('VAN_ADR', '')})"
            for o in rows[:7]
        ]
        # 좌표는 KATEC(GIS_X_COOR/GIS_Y_COOR)이라 WGS84 변환 부담 — map_points 는 생략, 출처 칩만 적재
        self.refs.append({"title": "오피넷 (한국석유공사 유가정보)",
                          "url": "https://www.opinet.co.kr"})
        return f"{region} {fuel} 최저가 주유소 상위 {len(parts)}곳 — " + "; ".join(parts)


@register_tool
class JejuDialectTool(BaseTool):
    name = "jeju_dialect"
    label = "제주 방언사전"
    theme = "dialect"
    description = ("제주 방언(사투리) 사전에서 단어를 검색해 표준어 뜻을 알려준다. "
                   "'하르방이 무슨 뜻' 같은 제주 사투리/방언 의미 질문에 사용. 부분 일치 검색 지원.")
    parameters = {
        "type": "object",
        "properties": {"word": {"type": "string", "description": "검색할 방언 단어 (예: 하르방, 할망)"}},
        "required": ["word"],
    }

    def enabled(self) -> bool:
        # 공개 API라 키 불요 — 항상 사용 가능
        return True

    async def run(self, word: str = "", **kwargs) -> str:
        if not word:
            return "검색할 방언 단어가 필요합니다."
        url = "https://www.jeju.go.kr/rest/JejuDialectService/getJejuDialectServiceList"
        try:
            # name 파라미터가 부분 일치 검색으로 동작한다 (word 파라미터는 무시됨을 실측 확인)
            r = await _get(url, {"name": word, "pageSize": 10})
        except httpx.HTTPError:
            return "제주 방언사전 조회 실패 (네트워크 오류)"
        entries: list[str] = []
        try:
            for item in ET.fromstring(r.content).iter("item"):
                name = (item.findtext("name") or "").replace("-", "").strip()
                meaning = " ".join((item.findtext("contents") or "").split())
                if name and meaning:
                    entries.append(f"{name}: {meaning}")
                if len(entries) >= 5:
                    break
        except ET.ParseError:
            return "제주 방언사전 조회 실패"
        if not entries:
            return f"'{word}' 방언 검색 결과가 없습니다."
        self.refs.append({"title": "제주도청 제주어사전",
                          "url": "https://www.jeju.go.kr/jejuword/index.htm"})
        return f"제주 방언사전 '{word}' 검색 결과 — " + "; ".join(entries)
