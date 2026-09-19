terraform {
  # State is kept in S3 so the eks/ configuration can read it later through
  # terraform_remote_state.
  #
  # The bucket is created once by scripts/create_state_bucket.sh and is not
  # managed by Terraform. If it were, "terraform destroy" would delete the
  # bucket together with the state file.
  #
  # use_lockfile makes Terraform keep the state lock in the same S3 bucket,
  # so no DynamoDB table is needed (Terraform 1.10+).
  backend "s3" {
    bucket       = "mlops-tfstate-goit-447ede"
    key          = "vpc/terraform.tfstate"
    region       = "us-east-1"
    profile      = "goit"
    encrypt      = true
    use_lockfile = true
  }
}
