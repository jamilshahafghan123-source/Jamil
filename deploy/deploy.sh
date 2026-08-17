#!/usr/bin/env bash
# =====================================================================
#  Deploy to Google Cloud.
#
#  Creates (idempotently): Artifact Registry repo, Cloud SQL Postgres,
#  Secret Manager entries, and two Cloud Run services.
#
#  It does NOT create the Windows VM that runs the MT5 bridge — see
#  deploy/windows-vm-setup.md for that, and run it first so you have the
#  bridge's internal IP.
#
#  Usage:
#    export PROJECT_ID=my-project
#    export MT5_BRIDGE_URL=http://10.128.0.5:8100
#    ./deploy/deploy.sh
# =====================================================================
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-europe-west1}"
REPO="${REPO:-mt5ai}"
SQL_INSTANCE="${SQL_INSTANCE:-mt5ai-db}"
DB_NAME="${DB_NAME:-mt5ai}"
DB_USER="${DB_USER:-mt5ai}"
CONNECTOR="${CONNECTOR:-mt5ai-connector}"
MT5_BRIDGE_URL="${MT5_BRIDGE_URL:?set MT5_BRIDGE_URL to the bridge VM, e.g. http://10.128.0.5:8100}"

AR="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}"

say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }

gcloud config set project "$PROJECT_ID" >/dev/null

say "Enabling APIs"
gcloud services enable \
  run.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com \
  vpcaccess.googleapis.com compute.googleapis.com

say "Artifact Registry"
gcloud artifacts repositories describe "$REPO" --location="$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "$REPO" \
    --repository-format=docker --location="$REGION" \
    --description="MT5 AI Trading Analyst"

say "Cloud SQL (Postgres 16)"
if ! gcloud sql instances describe "$SQL_INSTANCE" >/dev/null 2>&1; then
  gcloud sql instances create "$SQL_INSTANCE" \
    --database-version=POSTGRES_16 --tier=db-f1-micro --region="$REGION" \
    --storage-size=10GB --storage-auto-increase
fi
gcloud sql databases describe "$DB_NAME" --instance="$SQL_INSTANCE" >/dev/null 2>&1 || \
  gcloud sql databases create "$DB_NAME" --instance="$SQL_INSTANCE"

DB_PASSWORD="$(openssl rand -hex 24)"
gcloud sql users create "$DB_USER" --instance="$SQL_INSTANCE" --password="$DB_PASSWORD" \
  2>/dev/null || gcloud sql users set-password "$DB_USER" --instance="$SQL_INSTANCE" --password="$DB_PASSWORD"

CONN_NAME="$(gcloud sql instances describe "$SQL_INSTANCE" --format='value(connectionName)')"
DATABASE_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@/${DB_NAME}?host=/cloudsql/${CONN_NAME}"

say "Secret Manager"
put_secret() {
  local name="$1" value="$2"
  if gcloud secrets describe "$name" >/dev/null 2>&1; then
    printf '%s' "$value" | gcloud secrets versions add "$name" --data-file=- >/dev/null
  else
    printf '%s' "$value" | gcloud secrets create "$name" --data-file=- --replication-policy=automatic >/dev/null
  fi
  echo "  $name"
}

put_secret DATABASE_URL       "$DATABASE_URL"
put_secret JWT_SECRET         "${JWT_SECRET:-$(openssl rand -hex 32)}"
put_secret MT5_BRIDGE_TOKEN   "${MT5_BRIDGE_TOKEN:?set MT5_BRIDGE_TOKEN — must match the bridge host}"
put_secret ANTHROPIC_API_KEY  "${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY}"

say "Serverless VPC connector (so Cloud Run can reach the bridge VM privately)"
gcloud compute networks vpc-access connectors describe "$CONNECTOR" --region="$REGION" >/dev/null 2>&1 || \
  gcloud compute networks vpc-access connectors create "$CONNECTOR" \
    --region="$REGION" --network=default --range=10.8.0.0/28

say "Building images"
gcloud builds submit backend  --tag "${AR}/backend:latest"
gcloud builds submit frontend --tag "${AR}/frontend:latest"

say "Deploying backend"
gcloud run deploy mt5ai-backend \
  --image "${AR}/backend:latest" \
  --region "$REGION" \
  --platform managed \
  --no-allow-unauthenticated \
  --add-cloudsql-instances "$CONN_NAME" \
  --vpc-connector "$CONNECTOR" \
  --vpc-egress private-ranges-only \
  --set-env-vars "ENV=prod,SYMBOL=XAUUSD,ALLOW_REAL_TRADING=false,MT5_BRIDGE_URL=${MT5_BRIDGE_URL},ANALYST_MODEL=claude-opus-5,ANALYST_EFFORT=medium" \
  --set-secrets "DATABASE_URL=DATABASE_URL:latest,JWT_SECRET=JWT_SECRET:latest,MT5_BRIDGE_TOKEN=MT5_BRIDGE_TOKEN:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest" \
  --min-instances 1 \
  --max-instances 1 \
  --cpu 1 --memory 1Gi --timeout 300 --cpu-boost

# min=max=1 is deliberate: the bot loop and the in-process rate limiter both
# assume a single instance. Scaling out would run the bot N times per tick.

BACKEND_URL="$(gcloud run services describe mt5ai-backend --region "$REGION" --format='value(status.url)')"
echo "  backend: $BACKEND_URL"

say "Deploying frontend"
gcloud run deploy mt5ai-frontend \
  --image "${AR}/frontend:latest" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "BACKEND_URL=${BACKEND_URL},PORT=8080" \
  --max-instances 3 \
  --cpu 1 --memory 512Mi

FRONTEND_URL="$(gcloud run services describe mt5ai-frontend --region "$REGION" --format='value(status.url)')"

say "Allowing the frontend to invoke the backend"
FRONTEND_SA="$(gcloud run services describe mt5ai-frontend --region "$REGION" --format='value(spec.template.spec.serviceAccountName)')"
gcloud run services add-iam-policy-binding mt5ai-backend \
  --region "$REGION" --member "serviceAccount:${FRONTEND_SA}" --role roles/run.invoker >/dev/null

say "Setting CORS to the frontend origin"
gcloud run services update mt5ai-backend --region "$REGION" \
  --update-env-vars "CORS_ORIGINS=${FRONTEND_URL}" >/dev/null

cat <<EOF

  Done.

  Dashboard : ${FRONTEND_URL}
  Backend   : ${BACKEND_URL}
  Bridge    : ${MT5_BRIDGE_URL}   (must be reachable from the VPC connector)

  Next:
    1. Create the first user by redeploying once with BOOTSTRAP_EMAIL and
       BOOTSTRAP_PASSWORD set, then remove them:
         gcloud run services update mt5ai-backend --region ${REGION} \\
           --update-env-vars BOOTSTRAP_EMAIL=you@example.com,BOOTSTRAP_PASSWORD=<pw>
       ...sign in once, then:
         gcloud run services update mt5ai-backend --region ${REGION} \\
           --remove-env-vars BOOTSTRAP_EMAIL,BOOTSTRAP_PASSWORD
    2. Confirm the bridge is reachable:  curl ${BACKEND_URL}/ready
    3. REAL trading stays off until you set ALLOW_REAL_TRADING=true here AND
       BRIDGE_ALLOW_REAL=true on the Windows VM AND confirm in the UI.
EOF
