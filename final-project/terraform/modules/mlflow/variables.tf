variable "name_prefix" {
  description = "First part of the names of the IAM role and of the labels"
  type        = string
}

variable "cluster_name" {
  description = "Cluster the pod identity association belongs to"
  type        = string
}

variable "namespace" {
  description = "Namespace MLflow and its Postgres run in"
  type        = string
  default     = "mlops-system"
}

variable "service_account" {
  description = "Service account of the MLflow pod. It is created by Argo CD, not here."
  type        = string
  default     = "mlflow"
}

variable "bucket_prefix" {
  description = "First part of the bucket name. A random suffix is added, because bucket names are global."
  type        = string
  default     = "mlops-final-mlflow"
}

variable "postgres_secret_name" {
  description = "Name of the Kubernetes secret with the database credentials"
  type        = string
  default     = "mlflow-postgres"
}

variable "postgres_username" {
  description = "Database user MLflow connects with"
  type        = string
  default     = "mlflow"
}

variable "postgres_database" {
  description = "Database MLflow stores its tracking data in"
  type        = string
  default     = "mlflow"
}

variable "tags" {
  description = "Tags added to every AWS resource of the module"
  type        = map(string)
  default     = {}
}
