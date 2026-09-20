output "registry_url" {
  description = "Host part of every image, for example 123456789012.dkr.ecr.us-east-1.amazonaws.com"
  value       = local.registry_url
}

output "repository_urls" {
  description = "Full repository URL per service, without a tag"
  value       = { for name, repo in aws_ecr_repository.this : name => repo.repository_url }
}

output "repository_names" {
  description = "Repository name per service, for example training -> final-project/training"
  value       = { for name, repo in aws_ecr_repository.this : name => repo.name }
}

output "repository_arns" {
  description = "ARNs of the repositories, used to write a least privilege push policy"
  value       = [for repo in aws_ecr_repository.this : repo.arn]
}
