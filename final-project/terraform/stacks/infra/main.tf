# Stack 1 of 2: everything that has to exist before anything can run in the
# cluster. Apply this one first.
#
#   vpc        network, one NAT gateway
#   eks        cluster, one arm64 node group, add-ons, access entries
#   ecr        four image repositories
#   ci-access  GitHub OIDC provider and the role GitHub Actions assumes

locals {
  tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
    Stack     = "infra"
  }
}

module "vpc" {
  source = "../../modules/vpc"

  name                 = var.project_name
  cidr                 = var.vpc_cidr
  azs                  = var.azs
  private_subnet_cidrs = var.private_subnet_cidrs
  public_subnet_cidrs  = var.public_subnet_cidrs

  tags = local.tags
}

module "eks" {
  source = "../../modules/eks"

  cluster_name       = var.cluster_name
  kubernetes_version = var.kubernetes_version
  region             = var.aws_region

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  instance_types    = var.node_instance_types
  node_min_size     = var.node_min_size
  node_max_size     = var.node_max_size
  node_desired_size = var.node_desired_size

  mlops_engineer_group = var.mlops_engineer_group
  viewer_group         = var.viewer_group

  tags = local.tags
}

module "ecr" {
  source = "../../modules/ecr"

  name_prefix   = var.image_name_prefix
  service_names = var.service_names

  tags = local.tags
}

module "ci_access" {
  source = "../../modules/ci-access"

  name_prefix         = var.cluster_name
  github_repository   = var.github_repository
  github_branch       = var.github_branch
  ecr_repository_arns = module.ecr.repository_arns
  state_machine_name  = var.state_machine_name

  tags = local.tags
}
