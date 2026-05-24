"""
Unit tests for Cost Janitor.

Uses moto to mock AWS APIs at the SDK level — no LocalStack required.
Run with:  pytest janitor/tests/ -v
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import boto3
import pytest

# Make sure we can import from the janitor package
sys.path.insert(0, str(Path(__file__).parent.parent))

from moto import mock_aws
from janitor import (
    build_markdown,
    build_report,
    get_account_id,
    is_protected,
    missing_required_tags,
    scan_idle_eips,
    scan_missing_tags,
    scan_stopped_ec2,
    scan_unattached_ebs,
    tags_as_dict,
    main,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

REGION = "us-east-1"
FULL_TAGS = [
    {"Key": "Project", "Value": "nimbuskart"},
    {"Key": "Environment", "Value": "staging"},
    {"Key": "Owner", "Value": "platform-team"},
    {"Key": "ManagedBy", "Value": "terraform"},
]


def make_ec2_client():
    return boto3.client(
        "ec2",
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


# ── Tag helpers ───────────────────────────────────────────────────────────────

def test_tags_as_dict_normal():
    raw = [{"Key": "Project", "Value": "nimbuskart"}, {"Key": "Owner", "Value": "alice"}]
    assert tags_as_dict(raw) == {"Project": "nimbuskart", "Owner": "alice"}


def test_tags_as_dict_none():
    assert tags_as_dict(None) == {}


def test_tags_as_dict_empty():
    assert tags_as_dict([]) == {}


def test_is_protected_true():
    assert is_protected({"Protected": "true"}) is True


def test_is_protected_case_insensitive():
    assert is_protected({"Protected": "True"}) is True
    assert is_protected({"Protected": "TRUE"}) is True


def test_is_protected_false():
    assert is_protected({"Protected": "false"}) is False
    assert is_protected({}) is False


def test_missing_required_tags_all_present():
    tags = {"Project": "x", "Environment": "y", "Owner": "z"}
    assert missing_required_tags(tags) == []


def test_missing_required_tags_some_missing():
    tags = {"Project": "x"}
    missing = missing_required_tags(tags)
    assert "Environment" in missing
    assert "Owner" in missing


def test_missing_required_tags_all_missing():
    assert set(missing_required_tags({})) == {"Project", "Environment", "Owner"}


# ── EBS scanner ──────────────────────────────────────────────────────────────

@mock_aws
def test_scan_unattached_ebs_finds_orphan():
    ec2 = make_ec2_client()
    # Create an unattached volume
    ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=20, VolumeType="gp3", TagSpecifications=[
        {"ResourceType": "volume", "Tags": FULL_TAGS}
    ])

    findings = scan_unattached_ebs(ec2)
    assert len(findings) == 1
    assert findings[0]["resource_type"] == "ebs_volume"
    assert "unattached" in findings[0]["reason"]


@mock_aws
def test_scan_unattached_ebs_cost_calculation():
    ec2 = make_ec2_client()
    ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=100, VolumeType="gp3", TagSpecifications=[
        {"ResourceType": "volume", "Tags": FULL_TAGS}
    ])

    findings = scan_unattached_ebs(ec2)
    # 100 GB * $0.08/GB = $8.00
    assert findings[0]["estimated_monthly_cost_usd"] == 8.0


@mock_aws
def test_scan_unattached_ebs_protected_not_safe():
    ec2 = make_ec2_client()
    protected_tags = FULL_TAGS + [{"Key": "Protected", "Value": "true"}]
    ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=20, VolumeType="gp3", TagSpecifications=[
        {"ResourceType": "volume", "Tags": protected_tags}
    ])

    findings = scan_unattached_ebs(ec2)
    assert findings[0]["safe_to_auto_delete"] is False


@mock_aws
def test_scan_unattached_ebs_no_volumes():
    ec2 = make_ec2_client()
    findings = scan_unattached_ebs(ec2)
    assert findings == []


# ── EIP scanner ───────────────────────────────────────────────────────────────

@mock_aws
def test_scan_idle_eips_finds_unassociated():
    ec2 = make_ec2_client()
    ec2.allocate_address(Domain="vpc")

    findings = scan_idle_eips(ec2)
    assert len(findings) == 1
    assert findings[0]["resource_type"] == "elastic_ip"
    assert "unassociated" in findings[0]["reason"]


@mock_aws
def test_scan_idle_eips_cost():
    ec2 = make_ec2_client()
    ec2.allocate_address(Domain="vpc")

    findings = scan_idle_eips(ec2)
    assert findings[0]["estimated_monthly_cost_usd"] == 3.60


@mock_aws
def test_scan_idle_eips_no_idle():
    ec2 = make_ec2_client()
    # No EIPs allocated at all
    findings = scan_idle_eips(ec2)
    assert findings == []


# ── Missing tags scanner ──────────────────────────────────────────────────────

@mock_aws
def test_scan_missing_tags_catches_untagged_instance():
    ec2 = make_ec2_client()
    # Create an AMI first (moto needs a valid AMI)
    ami_response = ec2.describe_images(Owners=["amazon"])
    # Use moto's default ami or skip gracefully
    try:
        ami_id = ami_response["Images"][0]["ImageId"]
    except IndexError:
        pytest.skip("No AMI available in moto environment")

    ec2.run_instances(ImageId=ami_id, MinCount=1, MaxCount=1)
    findings = scan_missing_tags(ec2)
    # Instance has no tags at all — should be flagged
    assert any(f["resource_type"] == "ec2_instance" for f in findings)


# ── Report builder ────────────────────────────────────────────────────────────

def _sample_finding():
    return {
        "resource_id": "vol-abc123",
        "resource_type": "ebs_volume",
        "reason": "unattached",
        "age_days": 21,
        "estimated_monthly_cost_usd": 8.00,
        "tags": {"Project": None, "Environment": None, "Owner": None},
        "suggested_action": "delete",
        "safe_to_auto_delete": False,
    }


def test_build_report_schema():
    finding = _sample_finding()
    report = build_report([finding], "000000000000", "us-east-1")

    assert "scan_timestamp" in report
    assert report["account_id"] == "000000000000"
    assert report["region"] == "us-east-1"
    assert report["summary"]["total_orphans"] == 1
    assert report["summary"]["estimated_monthly_waste_usd"] == 8.0
    assert len(report["findings"]) == 1


def test_build_report_empty():
    report = build_report([], "000000000000", "us-east-1")
    assert report["summary"]["total_orphans"] == 0
    assert report["summary"]["estimated_monthly_waste_usd"] == 0.0


def test_build_markdown_contains_key_sections():
    finding = _sample_finding()
    report = build_report([finding], "000000000000", "us-east-1")
    md = build_markdown(report)

    assert "Cost Janitor Report" in md
    assert "vol-abc123" in md
    assert "ebs_volume" in md
    assert "$8.00" in md


def test_build_markdown_no_findings():
    report = build_report([], "000000000000", "us-east-1")
    md = build_markdown(report)
    assert "No orphaned resources found" in md


# ── Report JSON serialisability ───────────────────────────────────────────────

def test_report_is_json_serialisable():
    finding = _sample_finding()
    report = build_report([finding], "000000000000", "us-east-1")
    # Should not raise
    serialised = json.dumps(report)
    parsed = json.loads(serialised)
    assert parsed["summary"]["total_orphans"] == 1


# ── CLI exit codes ────────────────────────────────────────────────────────────

@mock_aws
def test_dry_run_exits_1_when_orphans_found(tmp_path):
    """Dry-run mode must exit 1 when orphans are present (so CI fails)."""
    ec2 = make_ec2_client()
    ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=20, VolumeType="gp3")

    # Do NOT pass --endpoint-url here: moto patches boto3 at the botocore level,
    # but only when no custom endpoint_url is provided. Passing localhost:4566
    # makes botocore bypass moto's intercept and try a real socket connection.
    exit_code = main([
        "--dry-run",
        "--region", REGION,
        "--output-dir", str(tmp_path),
    ])
    assert exit_code == 1


@mock_aws
def test_dry_run_exits_0_when_no_orphans(tmp_path):
    """Dry-run must exit 0 when nothing is found."""
    exit_code = main([
        "--dry-run",
        "--region", REGION,
        "--output-dir", str(tmp_path),
    ])
    assert exit_code == 0


@mock_aws
def test_output_files_created(tmp_path):
    """Both report.json and report.md must be written."""
    main([
        "--dry-run",
        "--region", REGION,
        "--output-dir", str(tmp_path),
    ])
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.md").exists()