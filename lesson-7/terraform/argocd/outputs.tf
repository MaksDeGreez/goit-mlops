output "namespace" {
  description = "Namespace Argo CD runs in"
  value       = helm_release.argocd.namespace
}

output "argocd_chart_version" {
  description = "Version of the installed argo-cd chart"
  value       = helm_release.argocd.version
}

output "gitops_repo_url" {
  description = "Repository the ApplicationSet watches"
  value       = var.gitops_repo_url
}

output "port_forward_command" {
  description = "Command that opens the Argo CD UI on http://localhost:8080"
  value       = "kubectl -n ${var.namespace} port-forward svc/argocd-server 8080:80"
}

output "argocd_admin_password" {
  description = "First password of the admin user in the Argo CD UI"
  value       = data.kubernetes_secret.argocd_admin.data["password"]
  sensitive   = true
}
