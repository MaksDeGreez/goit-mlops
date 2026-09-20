# The platform stack reads cluster_name, cluster_endpoint,
# cluster_certificate_authority_data, ecr_registry_url and the ECR repository
# URLs through terraform_remote_state. The rest is here for the reader.

output "cluster_name" {
  description = "Name of the EKS cluster"
  value       = module.eks.cluster_name
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

output "oidc_provider_arn" {
  description = "ARN of the OIDC provider of the cluster"
  value       = module.eks.oidc_provider_arn
}

output "vpc_id" {
  description = "ID of the VPC"
  value       = module.vpc.vpc_id
}

output "private_subnets" {
  description = "IDs of the private subnets, where the nodes run"
  value       = module.vpc.private_subnets
}

output "update_kubeconfig_command" {
  description = "Run this once to point kubectl at the cluster"
  value       = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.aws_region} --profile ${var.aws_profile}"
}

output "ecr_registry_url" {
  description = "Host part of every image. Terraform injects it into Argo CD, so it is never written into Git."
  value       = module.ecr.registry_url
}

output "ecr_repository_urls" {
  description = "Repository URL per service. CI pushes '<url>:<git sha>'."
  value       = module.ecr.repository_urls
}

output "ecr_login_command" {
  description = "Log the local Docker daemon in to the registry"
  value       = "aws ecr get-login-password --region ${var.aws_region} --profile ${var.aws_profile} | docker login --username AWS --password-stdin ${module.ecr.registry_url}"
}

output "ci_role_arn" {
  description = "ARN of the CI role. Set it as the repository variable AWS_ROLE_ARN in GitHub."
  value       = module.ci_access.role_arn
}

output "mlops_engineer_role_arn" {
  description = "Assume this role for full access inside the cluster (Kubernetes group mlops-engineers)"
  value       = module.eks.mlops_engineer_role_arn
}

output "viewer_role_arn" {
  description = "Assume this role for read only access inside the cluster (Kubernetes group viewers)"
  value       = module.eks.viewer_role_arn
}
