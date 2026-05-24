# ── Pricing Constants ─────────────────────────────────────────────────────────
# All prices are USD per month, us-east-1 on-demand as of 2024.
# Source: https://aws.amazon.com/ebs/pricing/ (accessed 2024-01)
#         https://aws.amazon.com/ec2/pricing/on-demand/ (accessed 2024-01)
#         https://aws.amazon.com/vpc/pricing/ (accessed 2024-01)

# EBS volume costs per GB per month
EBS_COST_PER_GB_MONTH = {
    "gp2": 0.10,   # General Purpose SSD gp2
    "gp3": 0.08,   # General Purpose SSD gp3  — source: aws.amazon.com/ebs/pricing
    "io1": 0.125,  # Provisioned IOPS SSD io1
    "io2": 0.125,  # Provisioned IOPS SSD io2
    "st1": 0.045,  # Throughput Optimized HDD
    "sc1": 0.015,  # Cold HDD
    "standard": 0.05,  # Magnetic (legacy)
}
EBS_DEFAULT_COST_PER_GB_MONTH = 0.08  # Fall back to gp3 price if type unknown

# EC2 t3.micro on-demand hourly cost × 730 hours/month
# Source: https://aws.amazon.com/ec2/pricing/on-demand/
EC2_STOPPED_COST_PER_MONTH = {
    # Stopped instances still incur EBS costs but NOT compute costs.
    # We report EBS-only cost for stopped instances.
    # For simplicity we use a flat estimate assuming 20 GB root volume (gp3).
    "default_root_gb": 20,
}

# Elastic IP: $0.005/hr when NOT associated with a running instance
# Source: https://aws.amazon.com/vpc/pricing/
EIP_IDLE_COST_PER_MONTH = 3.60  # $0.005 × 720 hrs

# Required tags every resource must carry
REQUIRED_TAGS = ["Project", "Environment", "Owner"]

# Tag that marks a resource as protected from auto-deletion
PROTECTED_TAG_KEY = "Protected"
PROTECTED_TAG_VALUE = "true"  # case-insensitive check applied in code

# Default threshold: instances stopped longer than this are flagged
DEFAULT_STOPPED_DAYS_THRESHOLD = 14