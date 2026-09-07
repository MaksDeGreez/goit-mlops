# The EKS configuration does not create any network resources itself.
# It reads the outputs of the vpc/ configuration straight from its state file
# in S3. This is why vpc/ must be applied first.
data "terraform_remote_state" "vpc" {
  backend = "s3"

  config = {
    bucket  = var.state_bucket
    key     = "vpc/terraform.tfstate"
    region  = var.aws_region
    profile = var.aws_profile
  }
}
