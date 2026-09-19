# Provider and version requirements for the project.

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  # Every resource gets these tags, which makes it easy to find and delete
  # everything that belongs to this task.
  default_tags {
    tags = {
      Project    = var.project_name
      Assignment = "lesson-10"
      ManagedBy  = "terraform"
    }
  }
}
