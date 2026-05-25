# Walkthrough — Cost Janitor Assignment

## Video

**Link:** [ADD YOUR LOOM / YOUTUBE UNLISTED LINK HERE]
**Length:** ~5 minutes

---

## Transcript / Notes

The video covers four things as required by the assignment brief:

### (a) Start LocalStack and apply Terraform live

```bash
git clone https://github.com/vishwajeet075/Cost-Janitor.git
cd Cost-Janitor

bash local_setup.sh
```

`local_setup.sh` does everything in one shot — checks prerequisites,
starts LocalStack 3.8.1 in Docker, creates a Python virtual environment,
installs dependencies, and runs `tflocal init` + `tflocal apply`.

Terraform creates 14 resources: VPC, internet gateway, 2 public subnets,
route table + 2 associations, security group, 2 EC2 instances (web tier),
S3 bucket + versioning + public access block, and the intentionally
unattached EBS volume that seeds Part B.

To inject additional orphans beyond what Terraform creates:

```bash
bash add_dummy_resources.sh
```

This adds 3 unattached EBS volumes, 2 stopped EC2 instances,
3 empty S3 buckets, and 3 unassociated Elastic IPs into the
running LocalStack environment.

### (b) Run the Janitor and walk through one finding

```bash
bash run_janitor.sh
```

The report shows the orphan EBS volume created by Terraform but never
attached. Key fields walked through live:

```json
{
  "resource_id": "vol-xxxxxxxx",
  "resource_type": "ebs_volume",
  "reason": "unattached",
  "age_days": 0,
  "estimated_monthly_cost_usd": 1.60,
  "tags": {
    "Project": "nimbuskart",
    "Environment": "staging",
    "Owner": "platform-team"
  },
  "suggested_action": "delete",
  "safe_to_auto_delete": true
}
```

Cost is `20 GB × $0.08/GB = $1.60/month`. `safe_to_auto_delete: true`
because all required tags are present and the `Protected` tag is absent.

Two report files are saved to `reports/` after every run:
- `reports/report.json` — machine-readable, full schema
- `reports/report.md` — human-readable summary with cost table

To also delete safe orphans:

```bash
bash run_janitor.sh --delete
```

### (c) One design decision I am proud of

The `continue-on-error: true` pattern on the janitor step in the GitHub
Actions workflow. A naive implementation would let the janitor's `exit 1`
abort the job immediately — before artifact upload and the PR comment
have run. By capturing the outcome in a subsequent step and deferring the
actual `exit 1` to the very last step, the pipeline always uploads the
report and posts the PR comment regardless of whether orphans were found.
This makes the failure actionable rather than just red.

### (d) One thing I would change

The stopped-EC2 scanner is fully implemented and covered by unit tests,
but cannot be demonstrated end-to-end in CI without stopping instances
after Terraform creates them. `add_dummy_resources.sh` handles this
locally (it stops 2 instances via `awslocal ec2 stop-instances`), but
the CI pipeline only runs Terraform apply with no post-apply stop step.
With more time I would add a `null_resource` with a `local-exec`
provisioner in Terraform that stops one web instance immediately after
creation, so the integration test in CI exercises all four scanners
against real provisioned infrastructure rather than three out of four.