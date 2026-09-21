terraform {
  # Same bucket as the infra stack, with its own key, so the two stacks keep
  # separate state files and can be applied and destroyed on their own.
  #
  # A backend block cannot use variables, so the profile is written out here.
  backend "s3" {
    bucket       = "mlops-tfstate-goit-447ede"
    key          = "final-project/platform/terraform.tfstate"
    region       = "us-east-1"
    profile      = "goit"
    encrypt      = true
    use_lockfile = true
  }
}
