# Submission — DevOps Engineer Assignment

**Candidate name:** Vishwajeet Shankar Shinde
**Email:** shindevishwajeet434@gmail.com
**Date submitted:** 25-05-2025
**Hours spent (approximate):** 8

## Deliverables checklist

- [x] Part A: Terraform code under /terraform applies cleanly on LocalStack
- [x] Part A: `terraform validate` and `terraform fmt -check` both pass
- [x] Part B: Janitor script runs in --dry-run mode and produces report.json
- [x] Part B: GitHub Actions workflow runs green on a fresh PR
- [x] Part B: --delete mode respects Protected=true tag
- [x] Part C: DESIGN.md is present and within 2 pages

## Walkthrough video

Link (Loom / YouTube unlisted / Google Drive): [ADD YOUR VIDEO LINK HERE]

## Sample report

Path to a sample report.json produced by your script: `reports/report.json`

## Known limitations

- `aws_s3_bucket_lifecycle_configuration` is commented out in `terraform/main.tf`. LocalStack 3.8.1 (the last free community version) hangs indefinitely on this resource's PUT API. The rule is preserved in code as a comment for real-AWS deployment — uncomment and apply.
- LocalStack 3.8.1 is pinned in CI because `localstack/localstack:latest` (v2026.5.x) now requires a paid `LOCALSTACK_AUTH_TOKEN` and exits with code 55 without one.
- The stopped-EC2 scanner is tested in unit tests (Moto) but cannot be demonstrated end-to-end in CI because stopping an instance programmatically after Terraform creates it would require an additional post-apply script. The scanner logic is fully implemented and unit-tested.
- Cost estimates use static prices from a `constants.py` file (sourced from aws.amazon.com/ebs/pricing, accessed 2024-01). Real-time pricing would require the AWS Pricing API.
- Delete mode is protected by `safe_to_auto_delete=false` for running instances and untagged resources, but has no human approval gate. Production use would require a manual trigger and acknowledgement step.

## AI usage disclosure

See README.md — ## AI usage disclosure section.
