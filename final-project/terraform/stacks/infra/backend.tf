terraform {
  # State is kept in S3, so the platform stack can read the outputs of this one
  # through terraform_remote_state, and so the state does not depend on which
  # branch happens to be checked out.
  #
  # The bucket was created once by hand (lesson-5/scripts/create_state_bucket.sh)
  # and is not managed by Terraform. If it were, "terraform destroy" would
  # delete the bucket together with the state file inside it.
  #
  # use_lockfile keeps the state lock in the same bucket, so no DynamoDB table
  # is needed (Terraform 1.10 and later).
  #
  # A backend block cannot use variables, so the profile is written out here.
  backend "s3" {
    bucket       = "mlops-tfstate-goit-447ede"
    key          = "final-project/infra/terraform.tfstate"
    region       = "us-east-1"
    profile      = "goit"
    encrypt      = true
    use_lockfile = true
  }
}
