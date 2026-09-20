variable "name_prefix" {
  description = "Value of the app.kubernetes.io/part-of label"
  type        = string
}

variable "namespace" {
  description = "Namespace the monitoring tools run in"
  type        = string
  default     = "monitoring"
}

variable "grafana_secret_name" {
  description = "Name of the Kubernetes secret with the Grafana admin login"
  type        = string
  default     = "grafana-admin"
}

variable "grafana_admin_user" {
  description = "Name of the Grafana admin user"
  type        = string
  default     = "admin"
}
