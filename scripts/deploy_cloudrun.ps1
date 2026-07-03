# 수동 Cloud Run 배포 (GitHub Actions 없이 로컬에서) — gcloud 사용자 계정으로 실행
# 사용: .\scripts\deploy_cloudrun.ps1
$ErrorActionPreference = "Stop"

$PROJECT = "project-65d06dcc-5794-483b-b6f"
$REGION = "asia-northeast3"
$IMAGE = "$REGION-docker.pkg.dev/$PROJECT/mlops-quicklab/jeju-genie:latest"
$ROOT = Split-Path $PSScriptRoot -Parent

Write-Host "[1/4] Cloud Run API 활성화 확인"
gcloud services enable run.googleapis.com --project $PROJECT

Write-Host "[2/4] 이미지 빌드 (linux/amd64, provenance off)"
docker build --provenance=false --sbom=false --platform linux/amd64 -t $IMAGE $ROOT

Write-Host "[3/4] Artifact Registry push"
gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet
docker push $IMAGE

Write-Host "[4/4] Cloud Run 배포"
$envVars = "GCS_BUCKET=$PROJECT-mlops-quicklab"
if ($env:OPENAI_API_KEY) { $envVars += ",OPENAI_API_KEY=$($env:OPENAI_API_KEY)" }
gcloud run deploy jeju-genie `
    --image $IMAGE `
    --region $REGION `
    --allow-unauthenticated `
    --memory 1Gi --cpu 1 `
    --min-instances 0 --max-instances 2 `
    --set-env-vars $envVars `
    --project $PROJECT

Write-Host "완료. 서비스 URL:"
gcloud run services describe jeju-genie --region $REGION --project $PROJECT --format "value(status.url)"
