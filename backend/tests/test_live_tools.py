# -*- coding: utf-8 -*-
"""실시간 도구(app/tools/jeju_live.py) 파싱 단위 테스트.

네트워크는 모듈의 _get 을 가짜 async 함수로 갈아끼워 차단한다.
pytest-asyncio 없이 asyncio.run 으로 코루틴을 직접 실행한다.
"""
import asyncio
import json

import httpx
import pytest

import app.tools.jeju_live as live
import app.tools.search_live as search


class FakeResponse:
    """httpx.Response 대역 — text/content/json()만 흉내낸다."""

    def __init__(self, text: str = "", json_data=None):
        if json_data is not None and not text:
            text = json.dumps(json_data, ensure_ascii=False)
        self.text = text
        self.content = text.encode("utf-8")
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("JSON 응답이 아님")
        return self._json


def patch_get(monkeypatch, response):
    """live._get 을 고정 응답 반환 함수로 교체. 호출 기록을 돌려준다."""
    calls = []

    async def _fake(url, params=None):
        calls.append((url, dict(params or {})))
        return response

    monkeypatch.setattr(live, "_get", _fake)
    return calls


def patch_get_error(monkeypatch):
    async def _fake(url, params=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(live, "_get", _fake)


def run(coro):
    return asyncio.run(coro)


# ── 공통 규약 ──────────────────────────────────────────────

def test_모든_도구_run_은_async_이고_theme_이_지정됨():
    themes = {
        "jeju_airport_weather": "weather",
        "jeju_fuel_price": "fuel",
        "jeju_realtime_traffic": "traffic",
        "jeju_place_search": "place",
        "jeju_statistics": "stats",
        "jeju_ev_charger": "ev",
        "jeju_gas_station": "fuel",
        "jeju_dialect": "dialect",
    }
    registry = {
        cls.name: cls for cls in [
            live.JejuWeatherTool, live.JejuFuelTool, live.JejuTrafficTool,
            live.JejuGeocodeTool, live.JejuDataHubStatTool,
            live.JejuEvChargerTool, live.JejuGasStationTool, live.JejuDialectTool,
        ]
    }
    assert set(registry) == set(themes)
    for name, cls in registry.items():
        assert asyncio.iscoroutinefunction(cls.run), f"{name}.run 이 async 가 아님"
        assert cls.theme == themes[name], f"{name} theme 불일치"


# ── 제주공항 METAR ─────────────────────────────────────────

METAR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<collect xmlns:iwxxm="http://icao.int/iwxxm/3.0">
  <iwxxm:airTemperature uom="Cel">26.0</iwxxm:airTemperature>
  <iwxxm:dewpointTemperature uom="Cel">22.0</iwxxm:dewpointTemperature>
  <iwxxm:meanWindDirection uom="deg">320</iwxxm:meanWindDirection>
  <iwxxm:meanWindSpeed uom="m/s">4</iwxxm:meanWindSpeed>
  <iwxxm:qnh uom="hPa">1008</iwxxm:qnh>
</collect>"""


def test_공항날씨_정상파싱(monkeypatch):
    patch_get(monkeypatch, FakeResponse(text=METAR_XML))
    out = run(live.JejuWeatherTool().run())
    assert "기온 26.0Cel" in out
    assert "풍속 4m/s" in out
    assert "RKPC" in out


def test_공항날씨_빈응답(monkeypatch):
    patch_get(monkeypatch, FakeResponse(text="<empty/>"))
    out = run(live.JejuWeatherTool().run())
    assert "실패" in out


# ── 제주 평균 유가 ─────────────────────────────────────────

def test_평균유가_정상파싱(monkeypatch):
    body = {"RESULT": {"OIL": [
        {"PRODCD": "B027", "PRODNM": "휘발유", "PRICE": "1743.36"},
        {"PRODCD": "D047", "PRODNM": "경유", "PRICE": "1620.11"},
    ]}}
    patch_get(monkeypatch, FakeResponse(json_data=body))
    out = run(live.JejuFuelTool().run())
    assert "휘발유: 1743.36원/L" in out
    assert "경유: 1620.11원/L" in out


def test_평균유가_빈응답(monkeypatch):
    patch_get(monkeypatch, FakeResponse(json_data={"RESULT": {"OIL": []}}))
    out = run(live.JejuFuelTool().run())
    assert "실패" in out


# ── 실시간 교통 ────────────────────────────────────────────

def test_교통_평균속도_계산(monkeypatch):
    body = {"info_cnt": 3, "info": [{"sped": 40}, {"sped": 60}, {"sped": 50}]}
    patch_get(monkeypatch, FakeResponse(json_data=body))
    out = run(live.JejuTrafficTool().run())
    assert "3개" in out
    assert "50.0km/h" in out


def test_교통_빈응답(monkeypatch):
    patch_get(monkeypatch, FakeResponse(json_data={"info": []}))
    out = run(live.JejuTrafficTool().run())
    assert "없음" in out


# ── 장소검색 ──────────────────────────────────────────────

def test_장소검색_정상파싱(monkeypatch):
    body = {"response": {"result": {"items": [{
        "title": "성산일출봉",
        "address": {"road": "제주 서귀포시 성산읍 일출로 284-12"},
        "point": {"x": "126.9425", "y": "33.4581"},
    }]}}}
    patch_get(monkeypatch, FakeResponse(json_data=body))
    out = run(live.JejuGeocodeTool().run(query="성산일출봉"))
    assert "성산일출봉" in out
    assert "126.9425" in out


def test_장소검색_결과없음(monkeypatch):
    body = {"response": {"result": {"items": []}}}
    patch_get(monkeypatch, FakeResponse(json_data=body))
    out = run(live.JejuGeocodeTool().run(query="없는곳"))
    assert "찾지 못했습니다" in out


def test_장소검색_제주밖_결과는_버림(monkeypatch):
    """지역어 제거 재시도가 육지 동명 업소(예: 부산 온천랜드)를 잡아도 제주 범위 필터로 걸러진다."""
    busan = {"response": {"result": {"items": [{
        "title": "온천랜드",
        "address": {"road": "부산광역시 동래구 어디로 1"},
        "point": {"x": "129.0730", "y": "35.2131"},
    }]}}}
    patch_get(monkeypatch, FakeResponse(json_data=busan))
    tool = live.JejuGeocodeTool()
    out = run(tool.run(query="서귀포 온천랜드"))
    assert "찾지 못했습니다" in out
    assert tool.map_points == [] and tool.refs == []


def test_장소검색_지역어제거_재시도(monkeypatch):
    """'서귀포 ○○' 조합이 NOT_FOUND 면 지역어를 떼고 한 번 더 검색한다 (VWorld 실측 보정)."""
    found = FakeResponse(json_data={"response": {"result": {"items": [{
        "title": "탐라사우나",
        "address": {"road": "제주 서귀포시 어디로 1"},
        "point": {"x": "126.5", "y": "33.5"},
    }]}}})
    empty = FakeResponse(json_data={"response": {"status": "NOT_FOUND"}})
    calls = []

    async def _fake(url, params=None):
        calls.append(params["query"])
        return found if params["query"] == "탐라사우나" else empty

    monkeypatch.setattr(live, "_get", _fake)
    tool = live.JejuGeocodeTool()
    out = run(tool.run(query="서귀포 탐라사우나"))
    assert calls == ["서귀포 탐라사우나", "탐라사우나"]
    assert "탐라사우나" in out
    assert tool.map_points == [{"name": "탐라사우나", "lat": 33.5, "lng": 126.5}]


# ── 데이터허브 통계 ────────────────────────────────────────

FAKE_SOURCES = {"jejudatahub": [
    {"name": "일별 버스 승객수", "apicode": "abc123"},
    {"name": "전기자동차 충전소 정보", "apicode": "ev999"},
]}


def test_통계_정상파싱(monkeypatch):
    monkeypatch.setattr(live, "load_sources", lambda: FAKE_SOURCES)
    monkeypatch.setattr(live.settings, "jejudatahub_project_key", "pk", raising=False)
    body = {"data": [{"date": "20260101", "count": 12345}]}
    calls = patch_get(monkeypatch, FakeResponse(json_data=body))
    out = run(live.JejuDataHubStatTool().run(keyword="버스 승객", start_date="20260101"))
    assert "일별 버스 승객수" in out
    assert "count:12345" in out
    assert "abc123" in calls[0][0]  # 매칭된 데이터셋 apicode 로 호출


def test_통계_빈데이터(monkeypatch):
    monkeypatch.setattr(live, "load_sources", lambda: FAKE_SOURCES)
    monkeypatch.setattr(live.settings, "jejudatahub_project_key", "pk", raising=False)
    patch_get(monkeypatch, FakeResponse(json_data={"data": []}))
    out = run(live.JejuDataHubStatTool().run(keyword="버스 승객", start_date="20260101"))
    assert "데이터가 없습니다" in out


def test_통계_데이터셋_미매칭(monkeypatch):
    monkeypatch.setattr(live, "load_sources", lambda: FAKE_SOURCES)
    out = run(live.JejuDataHubStatTool().run(keyword="존재안함", start_date="20260101"))
    assert "찾지 못했습니다" in out


# ── 전기차 충전소 ──────────────────────────────────────────

def test_충전소_지역검색(monkeypatch):
    monkeypatch.setattr(live, "load_sources", lambda: FAKE_SOURCES)
    monkeypatch.setattr(live.settings, "jejudatahub_project_key", "pk", raising=False)
    body = {"totCnt": 2, "data": [
        {"chargingPlace": "성산항 공영주차장", "quickChargerCount": 6, "chargerCount": 0,
         "startTime": "0:00", "endTime": "24:00"},
        {"chargingPlace": "성산일출봉 주차장", "quickChargerCount": 1, "chargerCount": 2,
         "startTime": "7:00", "endTime": "18:00"},
    ]}
    calls = patch_get(monkeypatch, FakeResponse(json_data=body))
    out = run(live.JejuEvChargerTool().run(region="성산", limit=5))
    assert "성산항 공영주차장(급속6·완속0" in out
    assert "'성산' 충전소 2곳" in out
    # 필터+페이지 파라미터를 섞으면 빈 응답이 오므로 chargingPlace 만 보내야 한다
    assert calls[0][1] == {"chargingPlace": "성산"}


def test_충전소_전역집계(monkeypatch):
    monkeypatch.setattr(live.settings, "jejuits_cits_code", "code", raising=False)
    body = {"info_cnt": 3, "info": [
        {"id": "A1", "fast": 2, "slow": 1},
        {"id": "A2", "fast": 0, "slow": 4},
        {"id": "A3", "fast": 1, "slow": 0},
    ]}
    patch_get(monkeypatch, FakeResponse(json_data=body))
    out = run(live.JejuEvChargerTool().run())
    assert "충전소 3곳" in out
    assert "급속 3기" in out
    assert "완속 5기" in out


def test_충전소_모두_빈응답(monkeypatch):
    monkeypatch.setattr(live, "load_sources", lambda: FAKE_SOURCES)
    monkeypatch.setattr(live.settings, "jejudatahub_project_key", "pk", raising=False)
    monkeypatch.setattr(live.settings, "jejuits_cits_code", "code", raising=False)
    patch_get(monkeypatch, FakeResponse(json_data={"totCnt": 0, "data": [], "info": []}))
    out = run(live.JejuEvChargerTool().run(region="없는곳"))
    assert "실패" in out


# ── 최저가 주유소 ──────────────────────────────────────────

def test_주유소_정상파싱(monkeypatch):
    monkeypatch.setattr(live.settings, "opinet_api_key", "k", raising=False)
    body = {"RESULT": {"OIL": [
        {"OS_NM": "성신주유소", "PRICE": 1895, "NEW_ADR": "제주 제주시 연삼로 159"},
        {"OS_NM": "오라주유소", "PRICE": 1895, "NEW_ADR": "", "VAN_ADR": "제주 제주시 오라2동"},
    ]}}
    calls = patch_get(monkeypatch, FakeResponse(json_data=body))
    out = run(live.JejuGasStationTool().run(region="서귀포시", fuel="경유"))
    assert "서귀포시 경유 최저가" in out
    assert "성신주유소 1895원/L" in out
    assert "오라주유소 1895원/L (제주 제주시 오라2동)" in out
    assert calls[0][1]["area"] == "1102"
    assert calls[0][1]["prodcd"] == "D047"


def test_주유소_빈응답(monkeypatch):
    monkeypatch.setattr(live.settings, "opinet_api_key", "k", raising=False)
    patch_get(monkeypatch, FakeResponse(json_data={"RESULT": {"OIL": []}}))
    out = run(live.JejuGasStationTool().run())
    assert "실패" in out


def test_주유소_네트워크오류(monkeypatch):
    monkeypatch.setattr(live.settings, "opinet_api_key", "k", raising=False)
    patch_get_error(monkeypatch)
    out = run(live.JejuGasStationTool().run())
    assert "네트워크 오류" in out


# ── 방언사전 ──────────────────────────────────────────────

DIALECT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<jejunetApi><error>false</error><result>SUCCESS</result>
<list>
  <item><seq>1</seq><name>하르방</name><contents>할아버지</contents></item>
  <item><seq>2</seq><name>하르-바님</name><contents>할아버님.
존칭</contents></item>
  <item><seq>3</seq><name>빈값</name><contents></contents></item>
</list></jejunetApi>"""


def test_방언_정상파싱(monkeypatch):
    calls = patch_get(monkeypatch, FakeResponse(text=DIALECT_XML))
    out = run(live.JejuDialectTool().run(word="하르"))
    assert "하르방: 할아버지" in out
    assert "하르바님: 할아버님. 존칭" in out  # 하이픈 제거 + 개행 정리
    assert "빈값" not in out  # 뜻 없는 항목 제외
    assert calls[0][1]["name"] == "하르"  # 실측: name 파라미터가 부분검색


def test_방언_결과없음(monkeypatch):
    empty = '<?xml version="1.0"?><jejunetApi><list/></jejunetApi>'
    patch_get(monkeypatch, FakeResponse(text=empty))
    out = run(live.JejuDialectTool().run(word="없는말"))
    assert "결과가 없습니다" in out


def test_방언_키없이_항상_enabled():
    assert live.JejuDialectTool().enabled() is True


def test_방언_정상시_출처칩_적재(monkeypatch):
    patch_get(monkeypatch, FakeResponse(text=DIALECT_XML))
    tool = live.JejuDialectTool()
    run(tool.run(word="하르"))
    assert any("jeju.go.kr" in ref["url"] for ref in tool.refs)


# ── 수집기(refs/map_points) 적재 — 기존 도구 개선분 ────────

def test_장소검색_지도마커와_네이버링크_적재(monkeypatch):
    body = {"response": {"result": {"items": [{
        "title": "성산일출봉",
        "address": {"road": "제주 서귀포시 성산읍 일출로 284-12"},
        "point": {"x": "126.9425", "y": "33.4581"},
    }]}}}
    patch_get(monkeypatch, FakeResponse(json_data=body))
    tool = live.JejuGeocodeTool()
    run(tool.run(query="성산일출봉"))
    assert tool.map_points == [{"name": "성산일출봉", "lat": 33.4581, "lng": 126.9425}]
    assert tool.refs and "map.naver.com/p/search/" in tool.refs[0]["url"]


def test_장소검색_결과없으면_수집기_비어있음(monkeypatch):
    patch_get(monkeypatch, FakeResponse(json_data={"response": {"result": {"items": []}}}))
    tool = live.JejuGeocodeTool()
    run(tool.run(query="없는곳"))
    assert tool.refs == [] and tool.map_points == []


def test_주유소_정상시_오피넷_출처칩(monkeypatch):
    monkeypatch.setattr(live.settings, "opinet_api_key", "k", raising=False)
    body = {"RESULT": {"OIL": [{"OS_NM": "성신주유소", "PRICE": 1895, "NEW_ADR": "제주"}]}}
    patch_get(monkeypatch, FakeResponse(json_data=body))
    tool = live.JejuGasStationTool()
    run(tool.run())
    assert any("opinet.co.kr" in ref["url"] for ref in tool.refs)
    assert tool.map_points == []  # KATEC 좌표는 변환 없이 생략


def test_충전소_지역검색_지도마커_적재(monkeypatch):
    monkeypatch.setattr(live, "load_sources", lambda: FAKE_SOURCES)
    monkeypatch.setattr(live.settings, "jejudatahub_project_key", "pk", raising=False)
    body = {"totCnt": 1, "data": [
        {"chargingPlace": "성산항 공영주차장", "quickChargerCount": 6, "chargerCount": 0,
         "startTime": "0:00", "endTime": "24:00",
         "latitude": 33.47234, "longitude": 126.932315},
    ]}
    patch_get(monkeypatch, FakeResponse(json_data=body))
    tool = live.JejuEvChargerTool()
    run(tool.run(region="성산"))
    assert tool.map_points == [{"name": "성산항 공영주차장", "lat": 33.47234, "lng": 126.932315}]


def test_충전소_좌표없는_행은_마커_생략(monkeypatch):
    monkeypatch.setattr(live, "load_sources", lambda: FAKE_SOURCES)
    monkeypatch.setattr(live.settings, "jejudatahub_project_key", "pk", raising=False)
    body = {"totCnt": 1, "data": [
        {"chargingPlace": "좌표없는곳", "quickChargerCount": 1, "chargerCount": 0,
         "startTime": "0:00", "endTime": "24:00"},
    ]}
    patch_get(monkeypatch, FakeResponse(json_data=body))
    tool = live.JejuEvChargerTool()
    out = run(tool.run(region="좌표"))
    assert "좌표없는곳" in out
    assert tool.map_points == []


# ── Visit Jeju 관광 검색 (search_live) ─────────────────────

def patch_search_get(monkeypatch, response):
    """search_live._get 을 고정 응답 함수로 교체. 호출 기록 반환."""
    calls = []

    async def _fake(url, params=None, headers=None):
        calls.append((url, dict(params or {})))
        return response

    monkeypatch.setattr(search, "_get", _fake)
    return calls


VISITJEJU_BODY = {
    "result": "200", "totalCount": 34, "resultCount": 2,
    "items": [
        {"title": "성산돌섬흑돼지",
         "contentsid": "CNTS_000000000022692",
         "contentscd": {"value": "c4", "label": "음식점"},
         "roadaddress": "제주 서귀포시 성산읍 일출로 1",
         "introduction": "성산 흑돼지 전문점",
         "latitude": 33.4689688, "longitude": 126.919785},
        {"title": "좌표없는집",
         "contentsid": "CNTS_000000000099999",
         "contentscd": {"value": "c4", "label": "음식점"},
         "address": "제주 서귀포시 성산읍",
         "introduction": "",
         "latitude": None, "longitude": None},
    ],
}


def test_관광검색_정상파싱_refs_map_적재(monkeypatch):
    monkeypatch.setattr(search.settings, "visitjeju_api_key", "vk", raising=False)
    calls = patch_search_get(monkeypatch, FakeResponse(json_data=VISITJEJU_BODY))
    tool = search.VisitJejuSearchTool()
    out = run(tool.run(query="성산", category="음식점"))
    assert "성산돌섬흑돼지" in out
    assert "[음식점]" in out
    assert "34건" in out
    # 실측: title= 이 키워드 검색, category= 가 contentscd 필터
    assert calls[0][1]["title"] == "성산"
    assert calls[0][1]["category"] == "c4"
    # refs: 상세 페이지 링크 2건, map_points: 좌표 있는 1건만
    assert [r["url"] for r in tool.refs] == [
        "https://www.visitjeju.net/kr/detail/view?contentsid=CNTS_000000000022692",
        "https://www.visitjeju.net/kr/detail/view?contentsid=CNTS_000000000099999",
    ]
    assert tool.map_points == [{"name": "성산돌섬흑돼지", "lat": 33.4689688, "lng": 126.919785}]


def test_관광검색_빈응답(monkeypatch):
    monkeypatch.setattr(search.settings, "visitjeju_api_key", "vk", raising=False)
    patch_search_get(monkeypatch, FakeResponse(json_data={"totalCount": 0, "items": []}))
    tool = search.VisitJejuSearchTool()
    out = run(tool.run(query="없는곳"))
    assert "없습니다" in out
    assert tool.refs == [] and tool.map_points == []


def test_관광검색_키없으면_비활성(monkeypatch):
    monkeypatch.setattr(search.settings, "visitjeju_api_key", None, raising=False)
    assert search.VisitJejuSearchTool().enabled() is False


# ── 위키백과 지식 검색 (search_live) ───────────────────────

def patch_wiki_get(monkeypatch, search_body, summaries):
    """URL에 따라 검색/요약 응답을 분기하는 가짜 _get. 호출 기록 반환."""
    calls = []

    async def _fake(url, params=None, headers=None):
        calls.append((url, dict(params or {})))
        if "w/api.php" in url:
            return FakeResponse(json_data=search_body)
        for key, body in summaries.items():
            if key in url:
                return FakeResponse(json_data=body)
        return FakeResponse(json_data={})

    monkeypatch.setattr(search, "_get", _fake)
    return calls


def test_위키검색_정상파싱_제주_접두어와_refs(monkeypatch):
    search_body = {"query": {"search": [{"title": "한라산"}, {"title": "성산일출봉"}]}}
    summaries = {
        "%ED%95%9C%EB%9D%BC%EC%82%B0": {  # quote("한라산")
            "extract": "한라산은 제주도 중앙부에 있는 화산이다.",
            "content_urls": {"desktop": {"page": "https://ko.wikipedia.org/wiki/한라산"}},
        },
    }
    calls = patch_wiki_get(monkeypatch, search_body, summaries)
    tool = search.JejuWikiSearchTool()
    out = run(tool.run(query="한라산 높이"))
    assert "한라산은 제주도 중앙부에 있는 화산이다." in out
    assert "성산일출봉" in out  # 요약 실패해도 제목은 포함
    # 검색어에 '제주'가 이미 있으면 그대로 사용
    assert calls[0][1]["srsearch"] == "제주 한라산 높이"
    assert len(tool.refs) == 2
    assert tool.refs[0]["url"] == "https://ko.wikipedia.org/wiki/한라산"
    assert tool.refs[1]["url"].startswith("https://ko.wikipedia.org/wiki/")


def test_위키검색_제주_포함시_접두어_생략(monkeypatch):
    calls = patch_wiki_get(monkeypatch, {"query": {"search": []}}, {})
    tool = search.JejuWikiSearchTool()
    out = run(tool.run(query="제주 4.3 사건"))
    assert calls[0][1]["srsearch"] == "제주 4.3 사건"
    assert "없습니다" in out
    assert tool.refs == []


def test_위키검색_키없이_항상_enabled():
    assert search.JejuWikiSearchTool().enabled() is True


def test_신규도구_theme_지정():
    assert search.VisitJejuSearchTool.theme == "place"
    assert search.JejuWikiSearchTool.theme == "knowledge"
