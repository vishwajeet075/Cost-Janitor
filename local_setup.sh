#!/usr/bin/env bash

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
header()  { echo -e "\n${BOLD}${CYAN}══════════════════════════════════════════${RESET}"; \
            echo -e "${BOLD}${CYAN}  $*${RESET}"; \
            echo -e "${BOLD}${CYAN}══════════════════════════════════════════${RESET}"; }

# ── argument parsing ──────────────────────────────────────────────────────────
FORCE_FRESH=false
for arg in "$@"; do
  case $arg in
    --fresh) FORCE_FRESH=true ;;
    --help|-h)
      echo "Usage: bash local_setup.sh [--fresh]"
      echo "  --fresh   Wipe and restart LocalStack + re-provision Terraform"
      exit 0 ;;
    *) warn "Unknown argument: $arg (ignored)" ;;
  esac
done

# ── config ────────────────────────────────────────────────────────────────────
LOCALSTACK_IMAGE="localstack/localstack:3.8.1"
LOCALSTACK_CONTAINER="localstack-nimbuskart"
LOCALSTACK_URL="http://localhost:4566"
AWS_REGION="us-east-1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── step 1: prerequisites ─────────────────────────────────────────────────────
header "Step 1 / 3 — Checking prerequisites"

check_cmd() {
  if command -v "$1" &>/dev/null; then
    success "$1 found"
  else
    error "$1 is not installed. Install: $2"; exit 1
  fi
}

check_cmd docker    "https://docs.docker.com/get-docker/"
check_cmd python3   "https://www.python.org/downloads/"
check_cmd terraform "https://developer.hashicorp.com/terraform/downloads"

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 11 ]]; }; then
  error "Python 3.11+ required, found $PY_VER"; exit 1
fi
success "Python $PY_VER — OK"

# ── step 2: LocalStack ────────────────────────────────────────────────────────
header "Step 2 / 3 — Starting LocalStack"

localstack_healthy() {
  curl -sf --max-time 5 "${LOCALSTACK_URL}/_localstack/health" -o /tmp/ls_health.json 2>/dev/null && grep -qE '"(running|available|initialized)"' /tmp/ls_health.json 2>/dev/null
}

if [[ "${FORCE_FRESH}" == "false" ]] && localstack_healthy; then
  warn "LocalStack is already running."
  warn "If you want a clean reset, run: bash local_setup.sh --fresh"
  warn "Otherwise infrastructure is already provisioned — you can run: bash run_janitor.sh"
  exit 0
fi

# Stop and remove existing container if present
if docker ps -q --filter "name=${LOCALSTACK_CONTAINER}" | grep -q .; then
  info "Stopping existing LocalStack container..."
  docker stop "${LOCALSTACK_CONTAINER}" >/dev/null
fi
if docker ps -aq --filter "name=${LOCALSTACK_CONTAINER}" | grep -q .; then
  docker rm "${LOCALSTACK_CONTAINER}" >/dev/null
fi

info "Starting LocalStack container..."
docker run --rm -d \
  -p 4566:4566 \
  -e SERVICES=ec2,s3,sts \
  -e AWS_DEFAULT_REGION="${AWS_REGION}" \
  -e AWS_ACCESS_KEY_ID=test \
  -e AWS_SECRET_ACCESS_KEY=test \
  --name "${LOCALSTACK_CONTAINER}" \
  "${LOCALSTACK_IMAGE}" >/dev/null

info "Waiting for LocalStack to be ready..."
RETRIES=30
until localstack_healthy; do
  RETRIES=$((RETRIES - 1))
  if [[ $RETRIES -le 0 ]]; then
    error "LocalStack did not become ready in time."
    docker logs "${LOCALSTACK_CONTAINER}" | tail -20
    exit 1
  fi
  echo -n "."; sleep 3
done
echo ""
success "LocalStack is ready."

# ── step 3: install deps + provision Terraform ────────────────────────────────
header "Step 3 / 3 — Installing dependencies + provisioning infrastructure"

cd "${SCRIPT_DIR}"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r janitor/requirements.txt
pip install -q terraform-local
success "Python dependencies installed."

export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION="${AWS_REGION}"

cd "${SCRIPT_DIR}/terraform"
info "Running tflocal init..."
tflocal init -upgrade -input=false -no-color 2>&1 | grep -E "(Initializing|provider|complete|Error)" || true
info "Running tflocal apply..."
tflocal apply -auto-approve -no-color 2>&1 | \
  grep -E "(aws_|Apply complete|Error|Warning)" | head -40 || true
success "Infrastructure provisioned."
cd "${SCRIPT_DIR}"

# ── done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}✓ Setup complete! LocalStack is running with base infrastructure.${RESET}"
echo ""
echo -e "${BOLD}Next steps:${RESET}"
echo -e "  ${CYAN}# (Optional) Add extra orphaned resources to test the janitor:${RESET}"
echo -e "  ${BOLD}bash add_dummy_resources.sh${RESET}"
echo ""
echo -e "  ${CYAN}# Run the Cost Janitor and see the report:${RESET}"
echo -e "  ${BOLD}bash run_janitor.sh${RESET}           ← dry-run (detect only)"
echo -e "  ${BOLD}bash run_janitor.sh --delete${RESET}  ← detect + clean up"
echo ""