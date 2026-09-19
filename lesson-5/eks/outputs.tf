output "cluster_name" {
  description = "Name of the EKS cluster"
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "Address of the Kubernetes API server"
  value       = module.eks.cluster_endpoint
}

output "cluster_version" {
  description = "Kubernetes version running on the control plane"
  value       = module.eks.cluster_version
}

output "cluster_security_group_id" {
  description = "Security group that the control plane uses to talk to the nodes"
  value       = module.eks.cluster_security_group_id
}

output "oidc_provider_arn" {
  description = "ARN of the OIDC provider of the cluster, needed later for IRSA"
  value       = module.eks.oidc_provider_arn
}

output "node_groups" {
  description = "Names of the managed node groups"
  value       = keys(module.eks.eks_managed_node_groups)
}

output "vpc_id" {
  description = "VPC the cluster runs in, read from the VPC remote state"
  value       = local.vpc_id
}

output "update_kubeconfig_command" {
  description = "Command that adds this cluster to the local kubeconfig"
  value       = "aws eks --region ${var.aws_region} --profile ${var.aws_profile} update-kubeconfig --name ${module.eks.cluster_name}"
}
