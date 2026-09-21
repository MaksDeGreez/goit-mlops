output "cluster_name" {
  description = "Name of the cluster"
  value       = module.eks.cluster_name
}

output "cluster_arn" {
  description = "ARN of the cluster"
  value       = module.eks.cluster_arn
}

output "cluster_endpoint" {
  description = "Address of the Kubernetes API server"
  value       = module.eks.cluster_endpoint
}

output "cluster_certificate_authority_data" {
  description = "Base64 encoded CA certificate of the API server"
  value       = module.eks.cluster_certificate_authority_data
}

output "cluster_version" {
  description = "Kubernetes version running on the control plane"
  value       = module.eks.cluster_version
}

output "cluster_security_group_id" {
  description = "Security group the control plane uses to talk to the nodes"
  value       = module.eks.cluster_security_group_id
}

output "oidc_provider_arn" {
  description = "ARN of the OIDC provider of the cluster"
  value       = module.eks.oidc_provider_arn
}

output "node_group_names" {
  description = "Names of the managed node groups"
  value       = keys(module.eks.eks_managed_node_groups)
}

output "mlops_engineer_role_arn" {
  description = "IAM role mapped to the Kubernetes group of the platform team"
  value       = aws_iam_role.mlops_engineer.arn
}

output "viewer_role_arn" {
  description = "IAM role mapped to the read only Kubernetes group"
  value       = aws_iam_role.viewer.arn
}
