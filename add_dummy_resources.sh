#!/usr/bin/env bash

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[+]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
header()  { echo -e "\n${BOLD}${CYAN}──────────────────────────────────────────${RESET}"; \
            echo -e "${BOLD}  $*${RESET}"; \
            echo -e "${BOLD}${CYAN}──────────────────────────────────────────${RESET}"; }

if ! command -v aws >/dev/null 2>&1; then
  echo -e "${RED}[ERROR]${RESET} aws CLI is not installed."
  echo "  → Install with: sudo apt install awscli -y"
  exit 1
fi

# ── AWS CLI wrapper pointing at LocalStack ────────────────────────────────────
ENDPOINT="http://localhost:4566"
REGION="us-east-1"

aws_local() {
  AWS_ACCESS_KEY_ID=test \
  AWS_SECRET_ACCESS_KEY=test \
  AWS_DEFAULT_REGION="${REGION}" \
  aws --endpoint-url "${ENDPOINT}" --region "${REGION}" "$@"
}

# ── check LocalStack is up ────────────────────────────────────────────────────
if ! curl -sf "${ENDPOINT}/_localstack/health" >/dev/null; then
  echo -e "${RED}[ERROR]${RESET} LocalStack is not reachable."
  echo "  → Run: bash local_setup.sh   (first)"
  exit 1
fi

# ── argument parsing ──────────────────────────────────────────────────────────
DO_EC2=false; DO_S3=false; DO_EIP=false; DO_ALL=true; LIST_ONLY=false

for arg in "$@"; do
  case $arg in
    --ec2)  DO_EC2=true;  DO_ALL=false ;;
    --s3)   DO_S3=true;   DO_ALL=false ;;
    --eip)  DO_EIP=true;  DO_ALL=false ;;
    --list) LIST_ONLY=true ;;
    --help|-h)
      sed -n '3,16p' "$0" | sed 's/^# \?//'
      exit 0 ;;
  esac
done

if [[ "${DO_ALL}" == "true" ]]; then
  DO_EC2=true; DO_S3=true; DO_EIP=true
fi

# ── list mode ─────────────────────────────────────────────────────────────────
if [[ "${LIST_ONLY}" == "true" ]]; then
  echo ""
  echo -e "${BOLD}Resources that would be created:${RESET}"
  [[ "${DO_EC2}" == "true" ]] && echo "  EC2  — 3 unattached EBS volumes (gp2, 50 GB each)"
  [[ "${DO_EC2}" == "true" ]] && echo "  EC2  — 2 stopped EC2 instances (t2.micro)"
  [[ "${DO_S3}"  == "true" ]] && echo "  S3   — 3 empty S3 buckets (simulate abandoned staging buckets)"
  [[ "${DO_EIP}" == "true" ]] && echo "  EIP  — 3 unassociated Elastic IPs"
  echo ""
  echo "Run without --list to actually create them."
  exit 0
fi

echo ""
echo -e "${BOLD}NimbusKart — Injecting Orphaned Resources into LocalStack${RESET}"
echo -e "These simulate real-world waste that the Cost Janitor should detect.\n"

# ── EC2: unattached EBS volumes ────────────────────────────────────────────────
if [[ "${DO_EC2}" == "true" ]]; then
  header "Unattached EBS Volumes (simulate forgotten snapshots / abandoned disks)"

  VOLUME_IDS=()
  for i in 1 2 3; do
    VOL_ID=$(aws_local ec2 create-volume \
      --availability-zone "${REGION}a" \
      --size 50 \
      --volume-type gp2 \
      --tag-specifications "ResourceType=volume,Tags=[{Key=Name,Value=orphan-vol-${i}},{Key=Env,Value=staging},{Key=Note,Value=dummy-for-testing}]" \
      --query 'VolumeId' --output text)
    VOLUME_IDS+=("$VOL_ID")
    success "Created unattached EBS volume: ${VOL_ID}  (orphan-vol-${i}, 50 GB)"
  done

  echo ""
  info "These volumes are NOT attached to any instance — the janitor should flag them."

  # ── EC2: stopped instances ─────────────────────────────────────────────────
  header "Stopped EC2 Instances (simulate forgotten dev boxes)"

  # Find the first available AMI in LocalStack
  AMI_ID=$(aws_local ec2 describe-images \
    --owners amazon \
    --query 'Images[0].ImageId' \
    --output text 2>/dev/null || echo "ami-00000000")

  for i in 1 2; do
    INSTANCE_ID=$(aws_local ec2 run-instances \
      --image-id "${AMI_ID}" \
      --instance-type t2.micro \
      --count 1 \
      --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=orphan-instance-${i}},{Key=Env,Value=staging},{Key=Note,Value=dummy-for-testing}]" \
      --query 'Instances[0].InstanceId' --output text)

    # Stop the instance to make it "stopped"
    aws_local ec2 stop-instances --instance-ids "${INSTANCE_ID}" >/dev/null
    success "Created + stopped EC2 instance: ${INSTANCE_ID}  (orphan-instance-${i})"
  done

  echo ""
  info "These instances are STOPPED — still incurring EBS charges. Janitor should flag them."
fi

# ── S3: empty buckets ──────────────────────────────────────────────────────────
if [[ "${DO_S3}" == "true" ]]; then
  header "Empty S3 Buckets (simulate abandoned staging / temp buckets)"

  BUCKET_NAMES=(
    "nimbuskart-staging-tmp-$(date +%s)-1"
    "nimbuskart-old-backups-$(date +%s)-2"
    "nimbuskart-abandoned-logs-$(date +%s)-3"
  )

  for BUCKET in "${BUCKET_NAMES[@]}"; do
    aws_local s3api create-bucket --bucket "${BUCKET}" >/dev/null
    # Tag it as old/orphaned
    aws_local s3api put-bucket-tagging \
      --bucket "${BUCKET}" \
      --tagging "TagSet=[{Key=Env,Value=staging},{Key=Status,Value=orphaned},{Key=Note,Value=dummy-for-testing}]"
    success "Created empty S3 bucket: ${BUCKET}"
  done

  echo ""
  info "These buckets are EMPTY and untagged with an owner — janitor should flag them."
fi

# ── EIP: unassociated Elastic IPs ─────────────────────────────────────────────
if [[ "${DO_EIP}" == "true" ]]; then
  header "Unassociated Elastic IPs (simulate forgotten IPs after instance termination)"

  for i in 1 2 3; do
    ALLOC=$(aws_local ec2 allocate-address \
      --domain vpc \
      --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=orphan-eip-${i}},{Key=Note,Value=dummy-for-testing}]" \
      --query 'AllocationId' --output text)
    success "Allocated unassociated Elastic IP: ${ALLOC}  (orphan-eip-${i})"
  done

  echo ""
  info "These EIPs are NOT associated with any instance — each costs ~\$3.60/month when idle."
fi

# ── summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}✓ Done! Orphaned resources injected.${RESET}"
echo ""
echo -e "${BOLD}Now re-run the janitor to see them detected:${RESET}"
echo ""
echo -e "  ${CYAN}# Dry-run — just detect, no deletion:${RESET}"
echo -e "  ${BOLD}bash local_setup.sh${RESET}"
echo ""
echo -e "  ${CYAN}# Delete mode — detect and remove:${RESET}"
echo -e "  ${BOLD}bash local_setup.sh --delete${RESET}"
echo ""
echo -e "  ${CYAN}# Or run the janitor directly:${RESET}"
echo -e "  ${BOLD}python3 janitor/janitor.py --dry-run --endpoint-url http://localhost:4566 --region us-east-1 --output-dir reports${RESET}"
echo ""