terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# When using tflocal, this block is automatically overridden to point
# all endpoints at LocalStack (http://localhost:4566).
# When running against real AWS, remove the endpoints block and
# supply real credentials via environment variables or ~/.aws/credentials.
provider "aws" {
  region = var.aws_region

  # LocalStack does not validate credentials — these are placeholders.
  # Never commit real keys here.
  access_key = "test"
  secret_key = "test"

  # tflocal injects these overrides automatically; they are shown here
  # explicitly so the file is self-documenting.
  endpoints {
    ec2 = "http://localhost:4566"
    s3  = "http://localhost:4566"
    iam = "http://localhost:4566"
  }

  # Required for LocalStack S3 to work correctly with path-style URLs
  s3_use_path_style = true

  # Suppress validation checks that fail against LocalStack
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
}
