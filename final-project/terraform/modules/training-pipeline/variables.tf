variable "name_prefix" {
  description = "First part of the names of the roles, the functions and the labels"
  type        = string
}

variable "state_machine_name" {
  description = "Name of the state machine. The CI role builds its ARN from this name, so keep both stacks in step."
  type        = string
  default     = "mlops-final-training"
}

variable "lambda_source_dir" {
  description = "Folder that holds validate_input.py and log_metrics.py"
  type        = string
}

# ---------------------------------------------------------------------------
# Cluster
# ---------------------------------------------------------------------------

variable "cluster_name" {
  description = "Cluster the training job runs in"
  type        = string
}

variable "cluster_endpoint" {
  description = "Address of the Kubernetes API server. Step Functions calls it directly, so it must be public."
  type        = string
}

variable "cluster_certificate_authority_data" {
  description = "Base64 encoded CA certificate of the API server"
  type        = string
}

variable "namespace" {
  description = "Namespace the training job runs in"
  type        = string
  default     = "mlops-system"
}

variable "training_service_account" {
  description = "Service account of the training job. It is created by Argo CD and needs no AWS rights."
  type        = string
  default     = "training"
}

variable "kubernetes_group" {
  description = "Kubernetes group the state machine role is mapped to by the access entry"
  type        = string
  default     = "stepfunctions-runners"
}

# ---------------------------------------------------------------------------
# The training job
# ---------------------------------------------------------------------------

variable "training_image_repository" {
  description = "ECR repository of the training image, without a tag. The tag comes from the pipeline input."
  type        = string
}

variable "job_name_prefix" {
  description = "First part of the name of every training Job"
  type        = string
  default     = "training"
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

variable "experiment_name" {
  description = "MLflow experiment the runs are written to"
  type        = string
  default     = "california-housing"
}

variable "job_cpu_request" {
  description = "CPU the training job asks for"
  type        = string
  default     = "500m"
}

variable "job_memory_request" {
  description = "Memory the training job asks for. The run on 20640 rows needs about a gigabyte."
  type        = string
  default     = "1Gi"
}

variable "job_memory_limit" {
  description = "Memory limit of the training job"
  type        = string
  default     = "1536Mi"
}

variable "job_ttl_seconds" {
  description = "How long a finished Job object stays before Kubernetes deletes it"
  type        = number
  default     = 900
}

variable "job_deadline_seconds" {
  description = "How long the job may run. Training itself takes well under a minute; the rest is pulling the image."
  type        = number
  default     = 1800
}

variable "job_log_tail_lines" {
  description = "How many log lines are brought back. The input and output of a state may not be larger than 256 KiB."
  type        = number
  default     = 100
}

# ---------------------------------------------------------------------------
# Lambda
# ---------------------------------------------------------------------------

variable "lambda_runtime" {
  description = "Python runtime of both functions"
  type        = string
  default     = "python3.13"
}

variable "lambda_architecture" {
  description = "CPU architecture of both functions. arm64 is about 20 percent cheaper than x86_64."
  type        = string
  default     = "arm64"
}

variable "lambda_memory_mb" {
  description = "Memory of both functions. They only parse JSON."
  type        = number
  default     = 128
}

variable "lambda_timeout_seconds" {
  description = "Timeout of both functions"
  type        = number
  default     = 30
}

variable "log_retention_days" {
  description = "How long CloudWatch keeps the logs of the pipeline"
  type        = number
  default     = 7
}

variable "tags" {
  description = "Tags added to every resource of the module"
  type        = map(string)
  default     = {}
}
