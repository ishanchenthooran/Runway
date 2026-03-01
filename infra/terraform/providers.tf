terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # Applies var.tags to every resource that supports default_tags,
  # so individual modules don't need to repeat the base tag set.
  default_tags {
    tags = var.tags
  }
}
