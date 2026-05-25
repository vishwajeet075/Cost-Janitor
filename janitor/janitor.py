"""
Cost Janitor — NimbusKart orphan resource scanner.

Usage:
    python janitor.py [--dry-run] [--delete] [--region REGION]
                        [--endpoint-url URL] [--stopped-days N]
                        [--output-dir DIR]

Modes:
    --dry-run   (default) Scan and report only. Exits non-zero if orphans found.
    --delete            Delete flagged resources. Skips anything tagged Protected=true.

Exit codes:
    0   No orphans found (dry-run) OR deletions completed (delete mode).
    1   Orphans found in dry-run mode.
    2   Unrecoverable error (auth failure, bad arguments, etc.).
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from constants import (
    DEFAULT_STOPPED_DAYS_THRESHOLD,
    EBS_COST_PER_GB_MONTH,
    EBS_DEFAULT_COST_PER_GB_MONTH,
    EIP_IDLE_COST_PER_MONTH,
    EC2_STOPPED_COST_PER_MONTH,
    PROTECTED_TAG_KEY,
    PROTECTED_TAG_VALUE,
    REQUIRED_TAGS,
)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("cost-janitor")


# ── Helpers ───────────────────────────────────────────────────────────────────

def tags_as_dict(tag_list: list | None) -> dict:
    """Convert AWS [{Key: ..., Value: ...}] tag list to a plain dict."""
    if not tag_list:
        return {}
    return {t["Key"]: t["Value"] for t in tag_list}


def is_protected(tags: dict) -> bool:
    """Return True if the resource carries Protected=true (case-insensitive)."""
    val = tags.get(PROTECTED_TAG_KEY, "")
    return val.lower() == PROTECTED_TAG_VALUE.lower()


def missing_required_tags(tags: dict) -> list[str]:
    """Return the list of REQUIRED_TAGS keys absent from tags dict."""
    return [k for k in REQUIRED_TAGS if not tags.get(k)]


def age_days(dt: datetime) -> int:
    """Return how many whole days have elapsed since dt (UTC-aware)."""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).days


def make_finding(
    resource_id: str,
    resource_type: str,
    reason: str,
    age_days_val: int,
    estimated_cost: float,
    tags: dict,
    suggested_action: str,
    safe_to_auto_delete: bool,
) -> dict:
    """Build a single findings entry matching the required report schema."""
    tag_snapshot = {k: tags.get(k) for k in REQUIRED_TAGS}
    return {
        "resource_id": resource_id,
        "resource_type": resource_type,
        "reason": reason,
        "age_days": age_days_val,
        "estimated_monthly_cost_usd": round(estimated_cost, 2),
        "tags": tag_snapshot,
        "suggested_action": suggested_action,
        "safe_to_auto_delete": safe_to_auto_delete,
    }


# ── Scanners ──────────────────────────────────────────────────────────────────

def scan_unattached_ebs(ec2) -> list[dict]:
    """
    Detect EBS volumes in 'available' state (not attached to any instance).
    Safe to auto-delete only when Protected != true AND no missing required tags
    (we want a human to review untagged volumes before deletion).
    """
    findings = []
    paginator = ec2.get_paginator("describe_volumes")

    for page in paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
        for vol in page["Volumes"]:
            vol_id = vol["VolumeId"]
            tags = tags_as_dict(vol.get("Tags"))
            size_gb = vol.get("Size", 0)
            vol_type = vol.get("VolumeType", "gp3")
            create_time = vol.get("CreateTime", datetime.now(timezone.utc))

            cost_per_gb = EBS_COST_PER_GB_MONTH.get(vol_type, EBS_DEFAULT_COST_PER_GB_MONTH)
            monthly_cost = size_gb * cost_per_gb

            missing = missing_required_tags(tags)
            protected = is_protected(tags)
            reasons = ["unattached"]
            if missing:
                reasons.append(f"missing_tags:{','.join(missing)}")

            # Auto-delete only if tagged correctly AND not protected
            safe = not protected and not missing

            findings.append(
                make_finding(
                    resource_id=vol_id,
                    resource_type="ebs_volume",
                    reason="|".join(reasons),
                    age_days_val=age_days(create_time),
                    estimated_cost=monthly_cost,
                    tags=tags,
                    suggested_action="delete",
                    safe_to_auto_delete=safe,
                )
            )
            log.info("Found unattached EBS volume: %s (%d GB %s, ~$%.2f/mo)", vol_id, size_gb, vol_type, monthly_cost)

    return findings


def scan_stopped_ec2(ec2, stopped_days_threshold: int) -> list[dict]:
    """
    Detect EC2 instances that have been in 'stopped' state for longer than
    stopped_days_threshold days.

    NOTE: Stopped instances do not incur compute charges but their attached EBS
    volumes continue to accrue costs. We estimate based on a default root volume.
    """
    findings = []
    paginator = ec2.get_paginator("describe_instances")

    for page in paginator.paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]
    ):
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                inst_id = inst["InstanceId"]
                tags = tags_as_dict(inst.get("Tags"))

                # StateTransitionReason carries the stop time for stopped instances
                # Format: "User initiated (2024-01-10 12:00:00 GMT)"
                stop_time = _parse_stop_time(inst.get("StateTransitionReason", ""))
                if stop_time is None:
                    # Cannot determine stop time — flag conservatively
                    stopped_age = stopped_days_threshold + 1
                else:
                    stopped_age = age_days(stop_time)

                if stopped_age < stopped_days_threshold:
                    continue

                # Cost estimate: root EBS volume only (compute is free while stopped)
                root_gb = EC2_STOPPED_COST_PER_MONTH["default_root_gb"]
                monthly_cost = root_gb * EBS_DEFAULT_COST_PER_GB_MONTH

                missing = missing_required_tags(tags)
                protected = is_protected(tags)
                reasons = [f"stopped>{stopped_days_threshold}d"]
                if missing:
                    reasons.append(f"missing_tags:{','.join(missing)}")

                safe = not protected and not missing

                findings.append(
                    make_finding(
                        resource_id=inst_id,
                        resource_type="ec2_instance",
                        reason="|".join(reasons),
                        age_days_val=stopped_age,
                        estimated_cost=monthly_cost,
                        tags=tags,
                        suggested_action="terminate",
                        safe_to_auto_delete=safe,
                    )
                )
                log.info(
                    "Found stopped EC2 instance: %s (stopped ~%d days, ~$%.2f/mo EBS)",
                    inst_id, stopped_age, monthly_cost,
                )

    return findings


def scan_idle_eips(ec2) -> list[dict]:
    """
    Detect Elastic IPs not associated with any running instance or network interface.
    Idle EIPs cost $0.005/hr (~$3.60/mo).
    """
    findings = []
    response = ec2.describe_addresses()

    for addr in response.get("Addresses", []):
        # Associated if it has an InstanceId or AssociationId
        if addr.get("InstanceId") or addr.get("AssociationId"):
            continue

        alloc_id = addr.get("AllocationId", addr.get("PublicIp", "unknown"))
        public_ip = addr.get("PublicIp", "unknown")
        tags = tags_as_dict(addr.get("Tags"))

        missing = missing_required_tags(tags)
        protected = is_protected(tags)
        reasons = ["unassociated"]
        if missing:
            reasons.append(f"missing_tags:{','.join(missing)}")

        safe = not protected and not missing

        findings.append(
            make_finding(
                resource_id=alloc_id,
                resource_type="elastic_ip",
                reason="|".join(reasons),
                age_days_val=0,  # AWS does not expose EIP allocation time in standard API
                estimated_cost=EIP_IDLE_COST_PER_MONTH,
                tags=tags,
                suggested_action="release",
                safe_to_auto_delete=safe,
            )
        )
        log.info("Found idle Elastic IP: %s (%s)", alloc_id, public_ip)

    return findings


def scan_missing_tags(ec2) -> list[dict]:
    """
    Detect EC2 instances and EBS volumes missing one or more required tags.
    Resources already caught by other scanners are NOT duplicated here —
    this catches tagged-but-running resources that are still missing tags.
    """
    findings = []

    # Check running instances (stopped ones are caught in scan_stopped_ec2)
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["running", "pending"]}]
    ):
        for reservation in page["Reservations"]:
            for inst in reservation["Instances"]:
                inst_id = inst["InstanceId"]
                tags = tags_as_dict(inst.get("Tags"))
                missing = missing_required_tags(tags)
                if not missing:
                    continue

                protected = is_protected(tags)
                findings.append(
                    make_finding(
                        resource_id=inst_id,
                        resource_type="ec2_instance",
                        reason=f"missing_tags:{','.join(missing)}",
                        age_days_val=age_days(inst.get("LaunchTime", datetime.now(timezone.utc))),
                        estimated_cost=0.0,  # Running instance cost unknown without instance type pricing
                        tags=tags,
                        suggested_action="tag",
                        safe_to_auto_delete=False,  # Never auto-delete a running instance
                    )
                )
                log.info("Running instance %s missing tags: %s", inst_id, missing)

    return findings


# ── Deletions ─────────────────────────────────────────────────────────────────

def delete_findings(ec2, findings: list[dict], dry_run: bool) -> dict[str, list]:
    """
    Attempt to delete/release/terminate resources in findings list.
    Always skips resources where safe_to_auto_delete is False.
    Returns dict with keys 'deleted' and 'skipped'.
    """
    deleted = []
    skipped = []

    for f in findings:
        rid = f["resource_id"]
        rtype = f["resource_type"]

        if not f["safe_to_auto_delete"]:
            log.info("SKIP %s %s (safe_to_auto_delete=false)", rtype, rid)
            skipped.append(rid)
            continue

        if dry_run:
            log.info("DRY-RUN would delete %s %s", rtype, rid)
            continue

        try:
            if rtype == "ebs_volume":
                ec2.delete_volume(VolumeId=rid)
                log.info("DELETED EBS volume %s", rid)
                deleted.append(rid)

            elif rtype == "ec2_instance":
                ec2.terminate_instances(InstanceIds=[rid])
                log.info("TERMINATED EC2 instance %s", rid)
                deleted.append(rid)

            elif rtype == "elastic_ip":
                ec2.release_address(AllocationId=rid)
                log.info("RELEASED Elastic IP %s", rid)
                deleted.append(rid)

            else:
                log.warning("Unknown resource type %s — skipping", rtype)
                skipped.append(rid)

        except ClientError as e:
            log.error("Failed to delete %s %s: %s", rtype, rid, e)
            skipped.append(rid)

    return {"deleted": deleted, "skipped": skipped}


# ── Report builders ───────────────────────────────────────────────────────────

def build_report(
    findings: list[dict],
    account_id: str,
    region: str,
) -> dict:
    """Assemble the final report.json structure."""
    total_waste = sum(f["estimated_monthly_cost_usd"] for f in findings)
    return {
        "scan_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "account_id": account_id,
        "region": region,
        "summary": {
            "total_orphans": len(findings),
            "estimated_monthly_waste_usd": round(total_waste, 2),
        },
        "findings": findings,
    }


def build_markdown(report: dict) -> str:
    """Build a human-readable Markdown summary from the report dict."""
    summary = report["summary"]
    findings = report["findings"]
    ts = report["scan_timestamp"]

    lines = [
        "# Cost Janitor Report",
        "",
        f"**Scan time:** {ts}  ",
        f"**Account:** `{report['account_id']}`  ",
        f"**Region:** `{report['region']}`  ",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total orphans found | **{summary['total_orphans']}** |",
        f"| Estimated monthly waste | **${summary['estimated_monthly_waste_usd']:.2f}** |",
        "",
    ]

    if not findings:
        lines += ["## No orphaned resources found.", ""]
        return "\n".join(lines)

    lines += ["## Findings", ""]
    lines += ["| Resource ID | Type | Reason | Age (days) | Est. Cost/mo | Safe to Delete |"]
    lines += ["|-------------|------|--------|-----------|-------------|----------------|"]

    for f in findings:
        safe = "Yes" if f["safe_to_auto_delete"] else "No"
        lines.append(
            f"| `{f['resource_id']}` "
            f"| {f['resource_type']} "
            f"| {f['reason']} "
            f"| {f['age_days']} "
            f"| ${f['estimated_monthly_cost_usd']:.2f} "
            f"| {safe} |"
        )

    lines += [
        "",
        "---",
        "> Resources marked are not safe to auto-delete.",
        "> They may be missing tags, carry `Protected=true`, or are running instances.",
        "> Review manually before taking action.",
        "",
    ]

    return "\n".join(lines)


# ── Utilities ─────────────────────────────────────────────────────────────────

def _parse_stop_time(reason: str) -> datetime | None:
    """
    Extract datetime from EC2 StateTransitionReason.
    Format: 'User initiated (2024-01-10 12:00:00 GMT)'
    """
    import re
    match = re.search(r"\((\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) GMT\)", reason)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def get_account_id(sts) -> str:
    """Return AWS account ID, falling back gracefully for LocalStack."""
    try:
        return sts.get_caller_identity()["Account"]
    except Exception:
        return "000000000000"


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cost Janitor — detect and optionally delete orphaned AWS resources."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Scan and report only. Exit non-zero if orphans found. (default)",
    )
    mode.add_argument(
        "--delete",
        action="store_true",
        default=False,
        help="Delete safe orphans. Skips Protected=true resources.",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        help="AWS region to scan (default: us-east-1)",
    )
    parser.add_argument(
        "--endpoint-url",
        default=os.getenv("AWS_ENDPOINT_URL", None),
        help="Custom endpoint URL (for LocalStack), e.g. http://localhost:4566",
    )
    parser.add_argument(
        "--stopped-days",
        type=int,
        default=DEFAULT_STOPPED_DAYS_THRESHOLD,
        help=f"Flag EC2 instances stopped longer than this many days (default: {DEFAULT_STOPPED_DAYS_THRESHOLD})",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory to write report.json and report.md (default: current dir)",
    )
    args = parser.parse_args(argv)
    # --delete implies NOT dry-run
    if args.delete:
        args.dry_run = False
    return args


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    mode_label = "DRY-RUN" if args.dry_run else "DELETE"
    log.info("=== Cost Janitor starting [mode=%s region=%s] ===", mode_label, args.region)

    # ── AWS clients ───────────────────────────────────────────────────────────
    client_kwargs: dict[str, Any] = {
        "region_name": args.region,
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID", "test"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
    }
    if args.endpoint_url:
        client_kwargs["endpoint_url"] = args.endpoint_url

    try:
        ec2 = boto3.client("ec2", **client_kwargs)
        sts = boto3.client("sts", **client_kwargs)
    except NoCredentialsError:
        log.error("No AWS credentials found. Set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY.")
        return 2

    account_id = get_account_id(sts)
    log.info("Account: %s | Region: %s", account_id, args.region)

    # ── Run all scanners ──────────────────────────────────────────────────────
    all_findings: list[dict] = []

    log.info("--- Scanning unattached EBS volumes ---")
    all_findings.extend(scan_unattached_ebs(ec2))

    log.info("--- Scanning stopped EC2 instances (threshold: %d days) ---", args.stopped_days)
    all_findings.extend(scan_stopped_ec2(ec2, args.stopped_days))

    log.info("--- Scanning idle Elastic IPs ---")
    all_findings.extend(scan_idle_eips(ec2))

    log.info("--- Scanning resources with missing required tags ---")
    all_findings.extend(scan_missing_tags(ec2))

    log.info("Total findings: %d", len(all_findings))

    # ── Delete mode ───────────────────────────────────────────────────────────
    if args.delete:
        log.info("--- Running in DELETE mode ---")
        result = delete_findings(ec2, all_findings, dry_run=False)
        log.info("Deleted: %d | Skipped: %d", len(result["deleted"]), len(result["skipped"]))

    # ── Build and write reports ───────────────────────────────────────────────
    report = build_report(all_findings, account_id, args.region)
    markdown = build_markdown(report)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report_json_path = output_dir / "report.json"
    report_md_path = output_dir / "report.md"

    report_json_path.write_text(json.dumps(report, indent=2, default=str))
    report_md_path.write_text(markdown)

    log.info("Reports written to %s", output_dir.resolve())
    log.info("  JSON : %s", report_json_path)
    log.info("  MD   : %s", report_md_path)

    if args.dry_run and all_findings:
        log.warning("Orphans found in dry-run mode — exiting with code 1")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())