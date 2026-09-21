output "namespace" {
  description = "Namespace Argo CD runs in"
  value       = helm_release.argocd.namespace
}

output "chart_version" {
  description = "Version of the installed argo-cd chart"
  value       = helm_release.argocd.version
}

output "root_application_name" {
  description = "Name of the root Application. Delete it first when tearing the project down."
  value       = var.root_application_name
}

output "port_forward_command" {
  description = "Opens the Argo CD UI on http://localhost:8080"
  value       = "kubectl -n ${var.namespace} port-forward svc/argocd-server 8080:80"
}

output "admin_password_command" {
  description = "Prints the first password of the Argo CD admin user"
  value       = "kubectl -n ${var.namespace} get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d"
}
