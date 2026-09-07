variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "Name of the AWS CLI profile used to create the resources"
  type        = string
  default     = "goit"
}

variable "project_name" {
  description = "Name prefix for all resources"
  type        = string
  default     = "mlops-train-automation"
}

variable "lambda_runtime" {
  description = "Python runtime for the Lambda functions"
  type        = string
  default     = "python3.13"
}

variable "lambda_architecture" {
  description = "CPU architecture for the Lambda functions. arm64 is about 20 percent cheaper than x86_64."
  type        = string
  default     = "arm64"
}

variable "lambda_memory_mb" {
  description = "Memory for the Lambda functions in megabytes"
  type        = number
  default     = 128
}

variable "lambda_timeout_seconds" {
  description = "Timeout for the Lambda functions in seconds"
  type        = number
  default     = 30
}

variable "log_retention_days" {
  description = "How long CloudWatch keeps the logs. A short retention keeps the cost near zero."
  type        = number
  default     = 7
}

variable "github_repository" {
  description = "GitHub repository allowed to start the workflow, in the form owner/name"
  type        = string
  default     = "MaksDeGreez/goit-mlops"
}

variable "github_branch" {
  description = "The only branch that is allowed to assume the CI role"
  type        = string
  default     = "lesson-10"
}
