terraform {
  # Same bucket as the VPC configuration, but a different key, so the two
  # configurations keep separate state files and can be applied and destroyed
  # on their own.
  backend "s3" {
    bucket       = "mlops-tfstate-goit-447ede"
    key          = "eks/terraform.tfstate"
    region       = "us-east-1"
    profile      = "goit"
    encrypt      = true
    use_lockfile = true
  }
}
