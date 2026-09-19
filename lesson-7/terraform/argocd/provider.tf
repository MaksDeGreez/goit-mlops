provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}

# The cluster was created in the previous assignment. Here we only need to
# talk to it, so we look it up by name instead of creating anything.
data "aws_eks_cluster" "this" {
  name = var.cluster_name
}

locals {
  cluster_host = data.aws_eks_cluster.this.endpoint
  cluster_ca   = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)

  # A short-lived token is fetched by the AWS CLI every time Terraform runs, so
  # no cluster credentials are ever written to disk or to the state file.
  cluster_exec = {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args = [
      "eks", "get-token",
      "--cluster-name", var.cluster_name,
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
