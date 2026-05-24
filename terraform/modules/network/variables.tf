variable "project" {
  description = "Project name used in resource names and tags"
  type        = string
}

variable "environment" {
  description = "Deployment environment (e.g. staging, prod)"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.20.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "List of CIDR blocks for public subnets (one per AZ)"
  type        = list(string)
  default     = ["10.20.1.0/24", "10.20.2.0/24"]
}

variable "availability_zones" {
  description = "List of AZs to deploy subnets into (must match length of public_subnet_cidrs)"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "common_tags" {
  description = "Common tags applied to all resources in this module"
  type        = map(string)
  default     = {}
}
