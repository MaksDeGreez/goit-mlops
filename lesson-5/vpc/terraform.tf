terraform {
  required_version = ">= 1.10"

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

  # Every resource created here gets these tags, so the whole assignment is
  # easy to find in the AWS console and easy to check for leftovers.
  default_tags {
    tags = {
      Project   = var.project_name
      Lesson    = "lesson-5"
      ManagedBy = "terraform"
    }
  }
}
