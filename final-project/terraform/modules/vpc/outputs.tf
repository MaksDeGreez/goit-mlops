output "vpc_id" {
  description = "ID of the VPC"
  value       = module.vpc.vpc_id
}

output "vpc_cidr_block" {
  description = "CIDR block of the VPC"
  value       = module.vpc.vpc_cidr_block
}

output "private_subnets" {
  description = "IDs of the private subnets, where the nodes run"
  value       = module.vpc.private_subnets
}

output "public_subnets" {
  description = "IDs of the public subnets, where the NAT gateway runs"
  value       = module.vpc.public_subnets
}

output "azs" {
  description = "Availability zones the subnets are spread over"
  value       = var.azs
}
