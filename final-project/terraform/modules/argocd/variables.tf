variable "namespace" {
  description = "Namespace Argo CD runs in. It is created by the stack, not by the chart."
  type        = string
  default     = "argocd"
}

variable "chart_version" {
  description = "Version of the argo-cd Helm chart"
  type        = string
  default     = "10.9.2"
}

variable "apps_chart_version" {
  description = "Version of the argocd-apps Helm chart that writes the root Application"
  type        = string
  default     = "2.0.5"
}

variable "root_application_name" {
  description = "Name of the root Application, the app of apps"
  type        = string
  default     = "mlops-platform"
}

variable "gitops_repo_url" {
  description = "HTTPS URL of the repository Argo CD reads. It is public, so no credentials are needed."
  type        = string
}

variable "gitops_revision" {
  description = "Branch of that repository to follow"
  type        = string
}

variable "bootstrap_path" {
  description = "Path of the app of apps chart inside the repository"
  type        = string
  default     = "final-project/gitops/bootstrap"
}

variable "image_registry" {
  description = "ECR registry host. Injected here because it contains the account id and must stay out of Git."
  type        = string
}

variable "aws_region" {
  description = "Region the cluster and the S3 bucket are in"
  type        = string
}

variable "mlflow_artifact_bucket" {
  description = "S3 bucket MLflow stores artifacts in. The name has a random suffix, so it is only known after apply."
  type        = string
}

variable "cluster_name" {
  description = "Name of the cluster, used by the cost dashboard and by the charts"
  type        = string
}
