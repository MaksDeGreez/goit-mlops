provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "terraform"
    }
  }
}

locals {
  cluster_host = data.terraform_remote_state.infra.outputs.cluster_endpoint
  cluster_ca   = base64decode(data.terraform_remote_state.infra.outputs.cluster_certificate_authority_data)

  # The AWS CLI fetches a short lived token every time Terraform runs, so no
  # cluster credentials are ever written to disk or into the state file.
  cluster_exec = {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args = [
      "eks", "get-token",
      "--cluster-name", data.terraform_remote_state.infra.outputs.cluster_name,
      "--region", var.aws_region,
      "--profile", var.aws_profile,
    ]
  }
}

provider "kubernetes" {
  host                   = local.cluster_host
  cluster_ca_certificate = local.cluster_ca

  exec {
    api_version = local.cluster_exec.api_version
    command     = local.cluster_exec.command
    args        = local.cluster_exec.args
  }
}

# The helm provider version 3 takes the cluster settings as one attribute
# instead of a block, and exec is an attribute too.
provider "helm" {
  kubernetes = {
    host                   = local.cluster_host
    cluster_ca_certificate = local.cluster_ca

    exec = {
      api_version = local.cluster_exec.api_version
      command     = local.cluster_exec.command
      args        = local.cluster_exec.args
    }
  }
}
