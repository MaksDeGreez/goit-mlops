# This stack creates no network and no cluster. It reads what it needs from the
# state file of the infra stack, which is why infra has to be applied first.
data "terraform_remote_state" "infra" {
  backend = "s3"

  config = {
    bucket  = var.state_bucket
    key     = "final-project/infra/terraform.tfstate"
    region  = var.aws_region
    profile = var.aws_profile
  }
}
