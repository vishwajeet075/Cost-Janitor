# NimbusKart Cost Hygiene — DevOps Assignment

## Overview

NimbusKart is a fictional e-commerce startup whose AWS bill grew from ~$400/month to ~$2,100/month due to orphaned resources. This repository contains three deliverables that together form a complete cost-hygiene foundation: Terraform infrastructure-as-code for the staging environment (Part A), a Python "Cost Janitor" script that detects and optionally deletes wasteful resources (Part B), and a GitHub Actions pipeline that enforces cost hygiene on every pull request (Part B CI/CD). A design note covering productionisation, multi-cloud extension, and safety is in `DESIGN.md` (Part C).

---

## How to run locally

### Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Docker | any recent | https://docs.docker.com/get-docker/ |
| Python | 3.11+ | https://www.python.org/downloads/ |
| Terraform | 1.7.x | https://developer.hashicorp.com/terraform/downloads |
| AWS CLI | any | https://aws.amazon.com/cli/ (needed for `add_dummy_resources.sh`) |

---

### Step 1 — Clone and set up infrastructure (run once)

```bash
git clone https://github.com/vishwajeet075/Cost-Janitor.git
cd Cost-Janitor

bash local_setup.sh
```

This script does everything in one go:
- Checks all prerequisites
- Starts LocalStack (mock AWS) in Docker
- Creates a Python virtual environment and installs dependencies
- Runs `tflocal init` + `tflocal apply` to provision the staging infrastructure

> If LocalStack is already running it exits early — no accidental re-provisioning.  
> To force a full reset: `bash local_setup.sh --fresh`

---

### Step 2 — (Optional) Inject extra orphaned resources

The Terraform provisioning already creates some orphaned resources for demo purposes. To add more — so you can see the janitor catch a wider variety of waste — run:

```bash
bash add_dummy_resources.sh
```

This injects into the running LocalStack:
- 3 unattached EBS volumes (50 GB gp2 each)
- 2 stopped EC2 instances (t2.micro)
- 3 empty S3 buckets (simulating abandoned staging/temp buckets)
- 3 unassociated Elastic IPs

You can also add specific resource types only:

```bash
bash add_dummy_resources.sh --ec2    # EBS volumes + stopped instances only
bash add_dummy_resources.sh --s3     # empty S3 buckets only
bash add_dummy_resources.sh --eip    # unassociated Elastic IPs only
bash add_dummy_resources.sh --list   # preview what would be created, no action
```

---

### Step 3 — Run the Cost Janitor

```bash
bash run_janitor.sh            # dry-run: detect and report, nothing deleted
bash run_janitor.sh --delete   # detect and delete safe orphans
```

The janitor scans for unattached EBS volumes, stopped EC2 instances, idle Elastic IPs, and resources with missing required tags. A report is printed to the terminal and saved to `reports/`.

---

### Full workflow summary

```
bash local_setup.sh            # once — start LocalStack + provision infra
bash add_dummy_resources.sh    # optional — inject extra orphans for testing
bash run_janitor.sh            # detect orphans + view report
bash run_janitor.sh --delete   # clean up orphans
```

To reset everything from scratch:

```bash
bash local_setup.sh --fresh    # stops LocalStack, re-provisions from zero
```

To run unit tests (no LocalStack needed — uses Moto):

```bash
cd janitor && pytest tests/ -v
```

---

### Reports

After running `run_janitor.sh`, two files are saved in `reports/`:

| File | Description |
|------|-------------|
| `reports/report.json` | Machine-readable full report with all findings |
| `reports/report.md` | Human-readable summary with resource list and cost estimates |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        GitHub Actions CI                        │
│                                                                 │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│  │ terraform-       │  │  unit-tests      │  │ cost-janitor │  │
│  │ validate         │  │  (Moto, no       │  │ (full        │  │
│  │                  │  │   Docker)        │  │  integration)│  │
│  │ fmt + init       │  │                  │  │              │  │
│  │ -backend=false   │  │  pytest          │  │  LocalStack  │  │
│  │ + validate       │  │  @mock_aws       │  │  3.8.1       │  │
│  └──────────────────┘  └──────────────────┘  │  ↓           │  │
│                                               │  tflocal     │  │
│                                               │  apply       │  │
│                                               │  ↓           │  │
│                                               │  janitor.py  │  │
│                                               │  --dry-run   │  │
│                                               │  ↓           │  │
│                                               │  report.json │  │
│                                               │  report.md   │  │
│                                               │  ↓           │  │
│                                               │  PR comment  │  │
│                                               │  + artifact  │  │
│                                               └──────────────┘  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     Repository Layout                           │
│                                                                 │
│  terraform/                                                     │
│  ├── main.tf          (SG, EC2 ×2, S3, orphan EBS)             │
│  ├── variables.tf     (all vars with defaults)                  │
│  ├── outputs.tf       (VPC ID, subnets, bucket, instance IDs)  │
│  └── modules/network/ (VPC, subnets, IGW, route table)         │
│                                                                 │
│  janitor/                                                       │
│  ├── janitor.py       (4 scanners, delete mode, report builder) │
│  ├── constants.py     (pricing constants with sources)          │
│  ├── requirements.txt                                           │
│  └── tests/           (pytest + Moto unit tests)               │
│                                                                 │
│  local_setup.sh           (start LocalStack + provision infra)  │
│  add_dummy_resources.sh   (inject extra orphans for testing)    │
│  run_janitor.sh           (run janitor + view reports)          │
│  .github/workflows/cost-janitor.yml  (3-job CI pipeline)       │
│  DESIGN.md            (Part C — productionisation design note)  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                  Cost Janitor — Scan Flow                       │
│                                                                 │
│  janitor.py                                                     │
│       │                                                         │
│       ├── scan_unattached_ebs()   →  EBS status=available       │
│       ├── scan_stopped_ec2()      →  stopped > N days           │
│       ├── scan_idle_eips()        →  no AssociationId           │
│       └── scan_missing_tags()     →  running, missing tags      │
│                                                                 │
│       ↓  all findings[]                                         │
│                                                                 │
│       build_report()  →  report.json                            │
│       build_markdown() →  report.md                             │
│                                                                 │
│       --dry-run  →  exit 1 if findings (CI fails)              │
│       --delete   →  skip Protected=true, delete rest            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Decisions & deviations

- **SSH CIDR default changed from `0.0.0.0/0` to `10.0.0.0/8`** — opening SSH to the entire internet is a critical security misconfiguration; a `validation` block in `variables.tf` rejects `0.0.0.0/0` entirely so the mistake cannot be reintroduced.
- **`aws_s3_bucket_lifecycle_configuration` commented out** — LocalStack 3.8.1 hangs indefinitely on this resource (S3 lifecycle PUT API never returns); the rule is preserved as a comment for real-AWS use.
- **LocalStack pinned to `3.8.1` in CI** — `localstack/localstack:latest` (v2026.5.x) now requires a paid `LOCALSTACK_AUTH_TOKEN`; 3.8.1 is the last free community release.
- **`ManagedBy` tag is hardcoded to `"terraform"` in `locals{}`** — it is not a variable because it should never be overridden; making it a variable would allow someone to provision Terraform resources and lie about how they were created.
- **`ami_id` defaults to `ami-0c55b159cbfafe1f0`** — LocalStack ignores the AMI value entirely; the default is Amazon Linux 2 us-east-1 as an illustrative placeholder for real-AWS use.
- **S3 bucket name is a variable with no random suffix** — for LocalStack this is fine; production would append `random_id` to guarantee global uniqueness.
- **Janitor does not scan RDS snapshots or Lambda functions** — the four required orphan types were prioritised; additional scanners can be added as provider methods without changing the core.

---

## Trade-offs

With one more week I would: (1) add a `--min-age-days` flag to the EBS scanner so volumes detached during a rolling deploy are not immediately flagged; (2) implement multi-account scanning using `sts:AssumeRole` in a loop over an AWS Organizations member list; (3) replace static pricing constants with live AWS Pricing API calls; (4) add a human approval gate before `--delete` runs in CI (a `workflow_dispatch` with a typed confirmation input); (5) emit CloudWatch metrics after every scan so the FinOps team gets trend visibility without reading raw JSON.

---

## AI usage disclosure

Claude (Anthropic) was used throughout this assignment for: scaffolding the GitHub Actions workflow YAML, debugging the LocalStack health-check timing issue, identifying the em-dash character in the security group description that caused AWS API validation to fail, drafting the DESIGN.md structure, and building the local setup scripts (`local_setup.sh`, `add_dummy_resources.sh`, `run_janitor.sh`).

**One thing AI got wrong:** Claude initially suggested using `localstack/localstack:latest` as the service container image. This caused the pipeline to fail immediately with exit code 55 because the latest LocalStack image now requires a paid auth token — something Claude's training data did not reflect. I identified the root cause from the container logs and pinned the image to `3.8.1`. Similarly, Claude's health-check used `grep '"ec2": "available"'` which never matched because LocalStack 3.8.1 reports service state as `"running"` not `"available"` — caught by running the scripts and reading the actual health endpoint response.

**One section written without AI:** The `_parse_stop_time()` function in `janitor.py` and its corresponding edge-case reasoning (what to do when `StateTransitionReason` is absent or malformed) was written manually. The EC2 API returns stop time buried inside a free-text string like `"User initiated (2024-01-10 12:00:00 GMT)"` rather than a proper timestamp field, and getting the regex and fallback behaviour right required reading the AWS docs directly and testing against real API responses rather than trusting generated code.