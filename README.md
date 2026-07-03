# 제주 지니 — RAG 기반 제주도 문답 챗 플랫폼

제주도에 관한 질문에 답하는 채팅 서비스이자, **데이터소스를 플러그인으로 확장하는 RAG 플랫폼**.
개발자는 커넥터 파일 하나와 API 키만 추가하면 새로운 제주 데이터가 챗봇 지식에 자동 편입된다.

```
[React 채팅 UI] --SSE--> [FastAPI] --검색--> [ChromaDB]
     말풍선/마스코트          |                   ^
                             v                   |
                        [LLM 추상화]        [ingest 파이프라인]
                     GPT(키 있으면) 또는          ^
                     Ollama(로컬 폴백)      [커넥터 플러그인들]
```

## 빠른 시작 (로컬)

```bash
# 1) 백엔드 준비
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt

# 2) 지식 인덱스 구축 (Ollama 필요: qwen3:14b, nomic-embed-text)
.venv/Scripts/python -m app.ingest --reset

# 3) 서버 실행 → http://localhost:8090
.venv/Scripts/python -m uvicorn app.main:app --port 8090
```

또는 Docker 한 방:

```bash
docker compose up -d --build     # http://localhost:8090
curl -X POST "http://localhost:8090/api/ingest?reset=true"   # 최초 1회 인덱스 구축
```

## 나중에 채우는 것들 (플랫폼 슬롯)

| 항목 | 넣는 곳 | 효과 |
|---|---|---|
| GPT API 키 | `.env` → `OPENAI_API_KEY=` | LLM/임베딩이 Ollama에서 GPT로 자동 전환 |
| 제주 API 키 | `.env` → `VISITJEJU_API_KEY=` 등 | 해당 커넥터가 활성화되어 ingest에 포함 |
| 마스코트 이미지 | `frontend/src/assets/` + `MascotSlot.tsx`의 교체 지점 | 헤더의 지니 캐릭터 교체 |
| UI 디자인 | `frontend/src/theme.css` (디자인 토큰) | 색/말풍선/폰트 일괄 교체 |

## 커넥터 추가하는 법 (개발자 가이드)

새 데이터소스 추가는 3단계다. 예: 제주 버스 정보 API.

1. `backend/app/connectors/jeju_bus.py` 생성:

```python
from app.config import settings
from app.connectors.base import BaseConnector, Document, register

@register
class JejuBusConnector(BaseConnector):
    name = "jeju_bus"

    def enabled(self) -> bool:
        return bool(settings.data_go_kr_api_key)   # 키 없으면 자동 skip

    def fetch(self) -> list[Document]:
        # API 호출 → Document(text=..., source="jeju_bus", title=..., url=...) 리스트 반환
        ...
```

2. 필요한 키를 `backend/app/config.py`와 `.env`에 추가.
3. `python -m app.ingest` 실행 — 끝. 커넥터는 자동 발견(discover)되며,
   `GET /api/sources`에서 활성 상태를 확인할 수 있다.

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/chat` | RAG 챗 (SSE: token/sources/done 이벤트) |
| POST | `/api/ingest?reset=&push=` | 인덱스 (재)구축, push=true면 GCS 업로드 |
| GET | `/api/sources` | 커넥터 목록/활성 상태 + 인덱스 청크 수 |
| GET | `/api/health` | LLM 프로바이더/인덱스 상태 |

## 배포 (MLOps)

- **CI/CD**: `.github/workflows/cicd.yml` — push 시 ruff+pytest → 이미지 빌드 →
  Artifact Registry push → Cloud Run 배포. GitHub Secrets 필요:
  `GCP_SA_KEY`, `GCP_PROJECT_ID`, `OPENAI_API_KEY`(선택).
- **수동 배포**: `scripts/deploy_cloudrun.ps1` (gcloud 사용자 계정).
- Cloud Run은 스테이트리스이므로 Chroma 인덱스는 GCS와 동기화한다:
  로컬에서 `python -m app.ingest --push` → 서비스 시작 시 자동 pull (`GCS_BUCKET` 환경변수).
- 주의: Cloud Run에는 Ollama가 없으므로 GPT 키가 없으면 챗이 "준비 중" 안내를 반환한다.
  GCS 인덱스도 GPT 임베딩으로 만들어 push해야 한다 (임베딩 모델별 컬렉션 분리됨).

## 테스트

```bash
cd backend && .venv/Scripts/python -m pytest tests/ -q
```
