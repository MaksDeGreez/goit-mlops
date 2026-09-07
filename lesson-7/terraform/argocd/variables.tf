variable "aws_region" {
  description = "AWS region the EKS cluster runs in"
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "Name of the AWS CLI profile to use"
  type        = string
  default     = "goit"
}

variable "cluster_name" {
  description = "Name of the existing EKS cluster (created in lesson-5)"
  type        = string
  default     = "goit-mlops-eks"
}

variable "namespace" {
  description = "Namespace for the platform tools, including Argo CD"
  type        = string
  default     = "infra-tools"
}

variable "argocd_chart_version" {
  description = "Version of the argo-cd Helm chart"
  type        = string
  default     = "10.8.2"
}

variable "argocd_apps_chart_version" {
  description = "Version of the argocd-apps Helm chart that holds the ApplicationSet"
  type        = string
  default     = "2.0.5"
}

variable "gitops_repo_url" {
  description = "HTTPS URL of the public GitOps repository that Argo CD watches"
  type        = string
  default     = "https://github.com/MaksDeGreez/goit-argo.git"
}

variable "gitops_repo_revision" {
  description = "Branch of the GitOps repository to follow"
  type        = string
  default     = "main"
}
