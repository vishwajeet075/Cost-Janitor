# DESIGN.md — Cost Janitor: Hardening, Scale, and Productionisation

## 1. Multi-Cloud Reality

To support GCP (and later Azure) without rewriting the core, the Janitor should adopt a **provider plugin architecture**. The core engine stays cloud-agnostic; each cloud gets its own adapter module that speaks the same internal interface.

```
janitor/
├── core/
│   ├── engine.py        # orchestrates scan → report → action
│   ├── models.py        # Finding dataclass, shared schema
│   └── report.py        # build_report(), build_markdown() — unchanged
├── providers/
│   ├── base.py          # Abstract class: scan_unattached_volumes(),
│   │                    #   scan_idle_ips(), scan_stopped_compute(),
│   │                    #   scan_missing_tags(), delete_resource()
│   ├── aws.py           # Current janitor.py logic, implements base.py
│   ├── gcp.py           # GCP adapter: Cloud Disks, static IPs, stopped VMs
│   └── azure.py         # Azure adapter: Managed Disks, Public IPs, deallocated VMs
└── janitor.py           # CLI: --provider aws|gcp|azure, delegates to adapter
```

Adding GCP means writing `gcp.py` that implements `base.py`. The engine, report schema, CI workflow, and deletion logic require zero changes. Credentials are injected via environment variables (`GOOGLE_APPLICATION_CREDENTIALS`, `AZURE_CLIENT_ID`, etc.) — the adapter reads them; the core never touches them.

---

## 2. Permissions

**Dry-run mode** needs read-only access only. Minimal IAM policy (JSON):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CostJanitorReadOnly",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeVolumes",
        "ec2:DescribeInstances",
        "ec2:DescribeAddresses",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
```

**Delete mode** adds the minimum destructive actions, scoped to deny Protected resources at the policy level as a second guardrail (the code check is the first):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CostJanitorReadOnly",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeVolumes",
        "ec2:DescribeInstances",
        "ec2:DescribeAddresses",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CostJanitorDelete",
      "Effect": "Allow",
      "Action": [
        "ec2:DeleteVolume",
        "ec2:TerminateInstances",
        "ec2:ReleaseAddress"
      ],
      "Resource": "*",
      "Condition": {
        "StringNotEqualsIgnoreCase": {
          "aws:ResourceTag/Protected": "true"
        }
      }
    }
  ]
}
```

The Janitor should run under a dedicated IAM role assumed via `sts:AssumeRole`, not long-lived access keys. The role is created by Terraform and scoped per account.

---

## 3. Safety Net — Two Failure Modes

**Failure mode 1: Volume detached mid-deploy, flagged as orphan, auto-deleted.**
During a rolling deployment, an EBS volume is temporarily detached while being re-attached to a new instance. If the Janitor runs in that window, the volume appears "available" and — if it passes all tag checks — gets deleted. The data is gone. Guardrails: (a) require the volume to be in `available` state for at least **7 days** before flagging it as safe to delete, not just momentarily; (b) check the volume's `CreateTime` AND its last `AttachTime` via CloudTrail before deleting; (c) enforce a minimum age threshold via `--min-age-days` flag, default 7.

**Failure mode 2: Auto-deletion runs during a production incident.**
An on-call engineer stops two web instances to diagnose a memory leak. They are correctly tagged but have been stopped for 15 days (over the threshold). The Janitor's nightly run terminates them automatically, removing the only evidence of the incident and taking capacity offline. Guardrails: (a) **delete mode should never run automatically on a schedule** — require a human to trigger it via a manual GitHub Actions `workflow_dispatch` with a required confirmation input; (b) add a `--max-deletions N` flag (default 5) so a single run cannot terminate more than N resources; (c) post a Slack/PagerDuty notification listing what will be deleted and require acknowledgement before proceeding (approval gate).

---

## 4. Observability

| Metric | Source | Alert threshold |
|--------|--------|-----------------|
| `janitor.orphans.total` | report.json `summary.total_orphans`, published to CloudWatch custom namespace `CostJanitor` after every scan | Alert if > 20 (runaway sprawl) |
| `janitor.waste.monthly_usd` | report.json `summary.estimated_monthly_waste_usd`, same namespace | Alert if > $500/month (budget breach) |
| `janitor.scan.duration_seconds` | Instrumented in `main()` with `time.perf_counter()`, emitted to CloudWatch | Alert if > 300s (scanning is hanging, likely API throttle) |
| `janitor.deletions.count` | Emitted after delete mode runs: `len(result["deleted"])` | Alert if > 10 in a single run (unusually destructive run) |
| `janitor.errors.count` | Count of `ClientError` exceptions caught in `delete_findings()` | Alert if > 0 (deletion silently failing) |

All five metrics are emitted via `boto3` `put_metric_data` into a `CostJanitor` CloudWatch namespace. A single CloudWatch dashboard surfaces all five. The FinOps team subscribes to an SNS topic that fires on any alert.

---

## 5. What I Did Not Build

The following were intentionally left out due to scope/time:

- **Multi-account scanning**  
  Current version assumes one account...

- **Additional resource types**  
  RDS snapshots and Lambda...

- **Approval gate before deletion**  
  Current delete mode uses a CLI flag...

- **Persistent scan history**  
  Current run overwrites `report.json`...

- **Live pricing integration**  
  Static per-unit pricing...
