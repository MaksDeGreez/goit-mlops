variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "Name of the AWS CLI profile to use"
  type        = string
  default     = "goit"
}

variable "project_name" {
  description = "Short name used as a prefix for resource names"
  type        = string
  default     = "goit-mlops"
}

variable "state_bucket" {
  description = "S3 bucket that holds the state file of the vpc/ configuration"
  type        = string
  default     = "mlops-tfstate-goit-447ede"
}

variable "cluster_name" {
  description = "Name of the EKS cluster"
  type        = string
  default     = "goit-mlops-eks"
}

variable "kubernetes_version" {
  description = "Kubernetes version of the EKS control plane"
  type        = string
  default     = "1.35"
}

variable "cpu_instance_types" {
  description = "Instance types for the cpu-nodes group (arm64 / Graviton)"
  type        = list(string)
  default     = ["t4g.medium"]
}

variable "gpu_instance_types" {
  description = "Instance types for the gpu-nodes group (x86_64)"
  type        = list(string)
  default     = ["t3.medium"]
}
