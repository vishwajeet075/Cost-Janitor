variable "aws_region" {
  description = "AWS region to deploy resources into"
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project name applied to all resource names and tags"
  type        = string
  default     = "nimbuskart"
}

variable "environment" {
  description = "Deployment environment name (used in tags and resource names)"
  type        = string
  default     = "staging"
}

variable "owner" {
  description = "Team or individual owning these resources (used in Owner tag)"
  type        = string
  default     = "platform-team"
}

# ── Network ───────────────────────────────────────────────────────────────────
variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.20.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for the two public subnets (one per AZ)"
  type        = list(string)
  default     = ["10.20.1.0/24", "10.20.2.0/24"]
}

variable "availability_zones" {
  description = "AZs to use for the public subnets"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

# ── Security ──────────────────────────────────────────────────────────────────
# DEVIATION: The spec defaults this to 0.0.0.0/0 — see README "Decisions & deviations".
# Default here is intentionally restrictive. Override with your actual bastion/VPN CIDR.
variable "ssh_allowed_cidr" {
  description = "CIDR allowed to reach port 22. Must NOT be 0.0.0.0/0 in any real environment."
  type        = string
  default     = "10.0.0.0/8"

  validation {
    condition     = var.ssh_allowed_cidr != "0.0.0.0/0"
    error_message = "Allowing SSH from 0.0.0.0/0 is not permitted. Provide a restricted CIDR (e.g. your VPN range)."
  }
}

# ── Compute ───────────────────────────────────────────────────────────────────
variable "web_instance_type" {
  description = "EC2 instance type for web tier nodes"
  type        = string
  default     = "t3.micro"
}

variable "web_instance_count" {
  description = "Number of web tier EC2 instances to create"
  type        = number
  default     = 2
}

variable "ami_id" {
  description = "AMI ID for EC2 instances. LocalStack accepts any non-empty string."
  type        = string
  default     = "ami-0c55b159cbfafe1f0" # Amazon Linux 2 us-east-1 (illustrative; LocalStack ignores value)
}

# ── Storage ───────────────────────────────────────────────────────────────────
variable "log_bucket_name" {
  description = "Name for the S3 application-log bucket. Must be globally unique."
  type        = string
  default     = "nimbuskart-staging-app-logs"
}

variable "noncurrent_version_expiry_days" {
  description = "Days after which non-current S3 object versions are expired"
  type        = number
  default     = 30
}

variable "orphan_ebs_size_gb" {
  description = "Size in GB of the intentionally unattached EBS volume (Part B orphan seed)"
  type        = number
  default     = 20
}
