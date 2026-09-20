# Network for the EKS cluster.
#
# Layout: two availability zones, one public and one private subnet in each.
# Worker nodes run in the private subnets, so they have no public IP address.
# They reach the internet (to pull images and to talk to S3 and ECR) through a
# NAT gateway that sits in a public subnet.

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 6.0"

  name = "${var.name}-vpc"
  cidr = var.cidr

  azs             = var.azs
  private_subnets = var.private_subnet_cidrs
  public_subnets  = var.public_subnet_cidrs

  # One NAT gateway for the whole VPC instead of one per zone. A NAT gateway
  # costs about $0.045 per hour, so this is the biggest saving in the project.
  # In production you would use one per zone, so the loss of a single zone
  # cannot cut off the others.
  enable_nat_gateway = true
  single_nat_gateway = true

  # EKS needs DNS names inside the VPC to register nodes.
  enable_dns_hostnames = true
  enable_dns_support   = true

  # These tags tell a load balancer controller which subnets it may use. The
  # project itself publishes nothing, but the tags cost nothing and they are
  # what every EKS guide expects to find.
  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"
  }

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = "1"
  }

  tags = var.tags
}
