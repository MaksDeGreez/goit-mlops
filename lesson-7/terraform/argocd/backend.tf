terraform {
  # Same S3 bucket as the VPC and EKS configurations of the previous
  # assignment, with its own key. The bucket is created once by hand and is
  # not managed by Terraform, so "terraform destroy" cannot delete the state.
  backend "s3" {
    bucket       = "mlops-tfstate-goit-447ede"
    key          = "argocd/terraform.tfstate"
    region       = "us-east-1"
    profile      = "goit"
    encrypt      = true
    use_lockfile = true
  }
}
