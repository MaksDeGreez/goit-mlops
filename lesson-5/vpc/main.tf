# Network for the EKS cluster that is created in the eks/ folder.
#
# Layout: two availability zones, one public and one private subnet in each.
# Worker nodes run in the private subnets, so they have no public IP address.
# They reach the internet (to pull container images) through a NAT gateway
# that sits in a public subnet.

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 6.0"

  name = "${var.project_name}-vpc"
  cidr = var.vpc_cidr

  azs             = var.azs
  private_subnets = var.private_subnet_cidrs
  public_subnets  = var.public_subnet_cidrs

  # One NAT gateway for the whole VPC instead of one per availability zone.
  # A NAT gateway costs about $0.045 per hour, so this keeps the price of the
  # learning environment down. In production you would use one per zone so the
  # loss of a single zone cannot cut off the others.
  enable_nat_gateway = true
  single_nat_gateway = true

  # EKS needs DNS names inside the VPC to register nodes.
  enable_dns_hostnames = true
  enable_dns_support   = true

  # These tags tell the AWS load balancer controller which subnets it may use:
  # public subnets for internet-facing load balancers, private subnets for
  # internal ones.
  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"
  }

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = "1"
  }
}
