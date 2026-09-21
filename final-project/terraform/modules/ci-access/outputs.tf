output "role_arn" {
  description = "ARN of the CI role. Set it as the repository variable FINAL_AWS_ROLE_ARN."
  value       = aws_iam_role.ci.arn
}

output "role_name" {
  description = "Name of the CI role"
  value       = aws_iam_role.ci.name
}

output "oidc_provider_arn" {
  description = "ARN of the GitHub OIDC provider"
  value       = aws_iam_openid_connect_provider.github.arn
}

output "state_machine_arn" {
  description = "ARN the CI role is allowed to start. Built from the name, see main.tf."
  value       = local.state_machine_arn
}
