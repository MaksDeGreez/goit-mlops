# No password is printed here. The two commands below read the secrets from the
# cluster when they are needed, so the values never end up in a terminal
# scrollback, in CI output or in a screenshot by accident.

output "state_machine_arn" {
  description = "ARN of the training pipeline. Set it as the repository variable FINAL_STATE_MACHINE_ARN in GitHub."
  value       = module.training_pipeline.state_machine_arn
}

output "start_training_command" {
  description = "Start a training run by hand, with the image tag and the commit of the build"
  value       = "aws stepfunctions start-execution --state-machine-arn ${module.training_pipeline.state_machine_arn} --region ${var.aws_region} --profile ${var.aws_profile} --input '{\"image_tag\":\"<tag>\",\"git_sha\":\"<sha>\"}'"
}

output "lambda_function_names" {
  description = "The two Lambda functions of the pipeline"
  value       = module.training_pipeline.lambda_function_names
}

output "mlflow_artifact_bucket" {
  description = "S3 bucket MLflow stores its models in. Versioning is on and it has a random suffix."
  value       = module.mlflow.artifact_bucket
}

output "mlflow_role_arn" {
  description = "IAM role the MLflow service account uses through Pod Identity"
  value       = module.mlflow.role_arn
}

output "namespaces" {
  description = "Namespaces created by this stack"
  value       = sort(keys(kubernetes_namespace_v1.this))
}

output "argocd_port_forward_command" {
  description = "Opens the Argo CD UI on http://localhost:8080"
  value       = module.argocd.port_forward_command
}

output "argocd_admin_password_command" {
  description = "Prints the first password of the Argo CD admin user. Run it, do not store the value."
  value       = module.argocd.admin_password_command
}

output "grafana_port_forward_command" {
  description = "Opens Grafana on http://localhost:3000, once Argo CD has deployed it"
  value       = "kubectl -n ${var.monitoring_namespace} port-forward svc/grafana 3000:80"
}

output "grafana_admin_password_command" {
  description = "Prints the Grafana admin password. Run it, do not store the value."
  value       = "kubectl -n ${var.monitoring_namespace} get secret ${module.monitoring.grafana_secret_name} -o jsonpath='{.data.admin-password}' | base64 -d"
}

output "mlflow_port_forward_command" {
  description = "Opens the MLflow UI on http://localhost:5000, once Argo CD has deployed it"
  value       = "kubectl -n ${var.mlops_namespace} port-forward svc/mlflow 5000:5000"
}

output "root_application_name" {
  description = "Delete this Application first when tearing the project down, and wait until it is gone"
  value       = module.argocd.root_application_name
}

output "delete_root_application_command" {
  description = "First step of the teardown: removes everything Argo CD created, including the volumes"
  value       = "kubectl -n ${var.argocd_namespace} delete application ${module.argocd.root_application_name}"
}
