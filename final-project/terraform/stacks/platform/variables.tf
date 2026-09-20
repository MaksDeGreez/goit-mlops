variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "Name of the AWS CLI profile to use. It is also used by 'aws eks get-token'."
  type        = string
  default     = "goit"
}

variable "project_name" {
  description = "Short name of the project, used in tags and in resource names"
  type        = string
  default     = "mlops-final"
}

variable "state_bucket" {
  description = "S3 bucket that holds the state file of the infra stack"
  type        = string
  default     = "mlops-tfstate-goit-447ede"
}

variable "namespaces" {
  description = "Namespaces of the project. Argo CD never creates one, so its Applications use CreateNamespace=false."
  type        = list(string)
  default     = ["argocd", "mlops-system", "monitoring", "staging", "production"]
}

variable "argocd_namespace" {
  description = "Namespace Argo CD runs in"
  type        = string
  default     = "argocd"
}

variable "mlops_namespace" {
  description = "Namespace for MLflow, Postgres, the training jobs and the drift job"
  type        = string
  default     = "mlops-system"
}

variable "monitoring_namespace" {
  description = "Namespace for Prometheus, Grafana, Loki and the rest"
  type        = string
  default     = "monitoring"
}

variable "gitops_repo_url" {
  description = "Repository Argo CD reads. It is public, so no credentials are needed."
  type        = string
  default     = "https://github.com/MaksDeGreez/goit-mlops.git"
}

variable "gitops_revision" {
  description = "Branch of that repository to follow"
  type        = string
  default     = "final-project"
}

variable "bootstrap_path" {
  description = "Path of the app of apps chart inside the repository"
  type        = string
  default     = "final-project/gitops/bootstrap"
}

variable "state_machine_name" {
  description = "Name of the training state machine. The CI role in the infra stack builds its ARN from this name."
  type        = string
  default     = "mlops-final-training"
}

variable "mlflow_tracking_uri" {
  description = "Address of the MLflow server inside the cluster"
  type        = string
  default     = "http://mlflow.mlops-system.svc.cluster.local:5000"
}

variable "model_name" {
  description = "Name of the model in the MLflow Model Registry"
  type        = string
  default     = "california-housing"
}
