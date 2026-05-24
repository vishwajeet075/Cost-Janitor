output "vpc_id" {
  description = "ID of the NimbusKart staging VPC"
  value       = module.network.vpc_id
}

output "public_subnet_ids" {
  description = "IDs of the two public subnets"
  value       = module.network.public_subnet_ids
}

output "public_subnet_cidrs" {
  description = "CIDR blocks of the two public subnets"
  value       = module.network.public_subnet_cidrs
}

output "bucket_name" {
  description = "Name of the S3 application-log bucket"
  value       = aws_s3_bucket.app_logs.id
}

output "web_instance_ids" {
  description = "IDs of the web tier EC2 instances"
  value       = aws_instance.web[*].id
}

output "orphan_ebs_volume_id" {
  description = "ID of the intentionally unattached EBS volume (Cost Janitor test target)"
  value       = aws_ebs_volume.orphan.id
}

output "web_security_group_id" {
  description = "ID of the web tier security group"
  value       = aws_security_group.web.id
}
