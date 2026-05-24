locals {
  # Single source of truth for mandatory tags applied to every resource.
  # All resources merge this map and add their own Name tag on top.
  common_tags = {
    Project     = var.project
    Environment = var.environment
    Owner       = var.owner
    ManagedBy   = "terraform"
  }
}

# ── Network (module) ──────────────────────────────────────────────────────────
module "network" {
  source = "./modules/network"

  project             = var.project
  environment         = var.environment
  vpc_cidr            = var.vpc_cidr
  public_subnet_cidrs = var.public_subnet_cidrs
  availability_zones  = var.availability_zones
  common_tags         = local.common_tags
}

# ── Security Group ────────────────────────────────────────────────────────────
resource "aws_security_group" "web" {
  name        = "${var.project}-${var.environment}-web-sg"
  description = "Web tier: allow HTTP/HTTPS from anywhere; SSH from restricted CIDR only"
  vpc_id      = module.network.vpc_id

  # HTTP
  ingress {
    description = "HTTP from anywhere"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTPS
  ingress {
    description = "HTTPS from anywhere"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # SSH — DEVIATION: spec says default 0.0.0.0/0; we require a restricted CIDR.
  # See README "Decisions & deviations" for rationale.
  # The variable has a validation block that rejects 0.0.0.0/0 entirely.
  ingress {
    description = "SSH from allowed CIDR only — never open to 0.0.0.0/0"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_allowed_cidr]
  }

  # Allow all outbound traffic (standard for application servers)
  egress {
    description = "All outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${var.project}-${var.environment}-web-sg"
  })
}

# ── EC2 Web Tier Instances ────────────────────────────────────────────────────
resource "aws_instance" "web" {
  count = var.web_instance_count

  ami                    = var.ami_id
  instance_type          = var.web_instance_type
  subnet_id              = module.network.public_subnet_ids[count.index % length(module.network.public_subnet_ids)]
  vpc_security_group_ids = [aws_security_group.web.id]

  tags = merge(local.common_tags, {
    Name = "${var.project}-${var.environment}-web-${count.index + 1}"
    Tier = "web"
  })
}

# ── S3 Application Log Bucket ─────────────────────────────────────────────────
resource "aws_s3_bucket" "app_logs" {
  bucket = var.log_bucket_name

  tags = merge(local.common_tags, {
    Name    = var.log_bucket_name
    Purpose = "application-logs"
  })
}

resource "aws_s3_bucket_versioning" "app_logs" {
  bucket = aws_s3_bucket.app_logs.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "app_logs" {
  bucket = aws_s3_bucket.app_logs.id

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_expiry_days
    }
  }
}

# Block all public access — logs must never be publicly readable.
resource "aws_s3_bucket_public_access_block" "app_logs" {
  bucket = aws_s3_bucket.app_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── Orphan EBS Volume (intentional — seed for Part B) ────────────────────────
# This volume is deliberately left unattached so the Cost Janitor can detect it.
# In a real account this pattern (available EBS volume) is one of the most
# common sources of silent waste.
resource "aws_ebs_volume" "orphan" {
  availability_zone = var.availability_zones[0]
  size              = var.orphan_ebs_size_gb
  type              = "gp3"

  # NOTE: Protected tag is intentionally absent — the Janitor should flag this.
  tags = merge(local.common_tags, {
    Name   = "${var.project}-${var.environment}-orphan-ebs"
    Notice = "intentional-orphan-for-cost-janitor-testing"
  })
}
