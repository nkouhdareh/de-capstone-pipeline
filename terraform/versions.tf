terraform {
  # >= 1.10 for use_lockfile (native S3 locking, no DynamoDB).
  # import blocks need >= 1.5.
  required_version = ">= 1.10"

  backend "s3" {
    bucket       = "de-capstone-tfstate-617371012792"
    key          = "ci-role/terraform.tfstate"
    region       = "eu-central-1"
    encrypt      = true
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = "eu-central-1"
}