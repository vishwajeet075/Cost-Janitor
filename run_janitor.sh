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
JANITOR_MODE="--dry-run"
for arg in "$@"; do
  case $arg in
    --delete) JANITOR_MODE="--delete" ;;
    --help|-h)
      echo "Usage: bash run_janitor.sh [--delete]"
      echo "  (no flag)  Dry-run — detect only, nothing deleted"
      echo "  --delete   Detect and remove orphaned resources"
      exit 0 ;;
    *) warn "Unknown argument: $arg (ignored)" ;;
  esac
done

# ── config ────────────────────────────────────────────────────────────────────
LOCALSTACK_URL="http://localhost:4566"
AWS_REGION="us-east-1"
REPORT_DIR="reports"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── check LocalStack is up ────────────────────────────────────────────────────
header "Checking LocalStack"

localstack_healthy() {
  # First check: port reachable at all
  if ! curl -sf --max-time 5 "${LOCALSTACK_URL}/_localstack/health" -o /tmp/ls_health.json 2>/dev/null; then
    return 1
  fi
  # Second check: response contains any running/available/initialized state
  # LocalStack 3.x uses "running", older used "available" — accept both
  if grep -qE '"(running|available|initialized)"' /tmp/ls_health.json 2>/dev/null; then
    return 0
  fi
  # Fallback: if we got ANY valid JSON response, the service is up enough
  if grep -q '{' /tmp/ls_health.json 2>/dev/null; then
    return 0
  fi
  return 1
}

if ! localstack_healthy; then
  error "LocalStack is not running or not reachable at ${LOCALSTACK_URL}."
  echo ""
  echo -e "  → Start it first with: ${BOLD}bash local_setup.sh${RESET}"
  exit 1
fi

# Show actual health status for visibility
HEALTH_SUMMARY=$(cat /tmp/ls_health.json 2>/dev/null | python3 -c "
import json,sys
try:
    d = json.load(sys.stdin)
    svcs = d.get('services', d)
    states = {k:v for k,v in svcs.items() if isinstance(v,str)}
    print(', '.join(f'{k}:{v}' for k,v in list(states.items())[:4]))
except:
    print('healthy')
" 2>/dev/null || echo "healthy")
success "LocalStack is running  [${HEALTH_SUMMARY}]"

# ── activate venv ─────────────────────────────────────────────────────────────
if [ ! -f "${SCRIPT_DIR}/.venv/bin/python" ]; then
  error ".venv not found. Run local_setup.sh first to install dependencies."
  exit 1
fi
source "${SCRIPT_DIR}/.venv/bin/activate"

# ── run janitor ───────────────────────────────────────────────────────────────
header "Running Cost Janitor  [mode: ${JANITOR_MODE}]"

mkdir -p "${REPORT_DIR}"

export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION="${AWS_REGION}"

set +e
"${SCRIPT_DIR}/.venv/bin/python" janitor/janitor.py \
  ${JANITOR_MODE} \
  --endpoint-url "${LOCALSTACK_URL}" \
  --region "${AWS_REGION}" \
  --output-dir "${REPORT_DIR}"
JANITOR_EXIT=$?
set -e

if [[ $JANITOR_EXIT -gt 1 ]]; then
  error "Janitor exited with code $JANITOR_EXIT — check output above."
  exit $JANITOR_EXIT
fi
success "Janitor completed."

# ── show report ───────────────────────────────────────────────────────────────
header "Report Summary"

if [[ -f "${REPORT_DIR}/report.md" ]]; then
  echo ""
  cat "${REPORT_DIR}/report.md"
elif [[ -f "${REPORT_DIR}/report.json" ]]; then
  echo ""
  "${SCRIPT_DIR}/.venv/bin/python" -c "
import json
with open('${REPORT_DIR}/report.json') as f:
    r = json.load(f)
total = r.get('total_orphaned_resources', r.get('summary', {}).get('total', '?'))
cost  = r.get('estimated_monthly_waste_usd', r.get('summary', {}).get('estimated_waste_usd', '?'))
print(f'  Orphaned resources found : {total}')
print(f'  Estimated monthly waste  : \${cost}')
"
else
  warn "No report found in ${REPORT_DIR}/ — check janitor output above."
fi

echo ""
echo -e "${BOLD}Full reports saved to:${RESET}"
echo -e "  ${GREEN}${SCRIPT_DIR}/${REPORT_DIR}/report.json${RESET}"
echo -e "  ${GREEN}${SCRIPT_DIR}/${REPORT_DIR}/report.md${RESET}"
echo ""

if [[ "${JANITOR_MODE}" == "--dry-run" ]]; then
  echo -e "${YELLOW}ℹ DRY-RUN — no resources were deleted.${RESET}"
  echo -e "   To delete orphans: ${BOLD}bash run_janitor.sh --delete${RESET}"
fi
echo ""