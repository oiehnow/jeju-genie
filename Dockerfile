# 제주 지니 — 멀티스테이지 빌드 (frontend build → backend + 정적 서빙)
#
# 빌드/푸시 (Artifact Registry, Cloud Run용):
#   docker build --provenance=false --sbom=false --platform linux/amd64 \
#     -t asia-northeast3-docker.pkg.dev/<PROJECT>/mlops-quicklab/jeju-genie:latest .

# ── 1단계: 프론트엔드 빌드 ──────────────────────────────
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --silent
COPY frontend/ ./
RUN npm run build

# ── 2단계: 백엔드 + 정적 파일 ───────────────────────────
FROM python:3.11-slim
WORKDIR /srv

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/data ./data
COPY --from=frontend /build/dist ./static

ENV PORT=8080 \
    SEED_DOCS_DIR=/srv/data/seed \
    CHROMA_DIR=/srv/chroma_data \
    ANONYMIZED_TELEMETRY=False

EXPOSE 8080
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
