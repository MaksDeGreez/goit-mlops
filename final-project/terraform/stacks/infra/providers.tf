provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  # Every resource created here gets these tags, so the whole project is easy
  # to find in the console and easy to check for leftovers after a destroy.
  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "terraform"
    }
  }
}
