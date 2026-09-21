output "grafana_secret_name" {
  description = "Kubernetes secret with the keys admin-user and admin-password"
  value       = kubernetes_secret_v1.grafana_admin.metadata[0].name
}

output "grafana_admin_user" {
  description = "Name of the Grafana admin user"
  value       = var.grafana_admin_user
}
