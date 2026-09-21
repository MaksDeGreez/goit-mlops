variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "Name of the AWS CLI profile to use. The account has a second, unrelated profile."
  type        = string
  default     = "goit"
}

variable "project_name" {
  description = "Short name of the project, used in tags"
  type        = string
  default     = "mlops-final"
}

variable "cluster_name" {
  description = "Name of the EKS cluster. It is also the prefix of the IAM roles of the project."
  type        = string
  default     = "mlops-final"
}

variable "kubernetes_version" {
  description = "Kubernetes version of the control plane"
  type        = string
  default     = "1.35"
}

variable "vpc_cidr" {
  description = "CIDR block of the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "azs" {
  description = "Availability zones. EKS needs at least two."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks of the private subnets, one per zone"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks of the public subnets, one per zone"
  type        = list(string)
  default     = ["10.0.101.0/24", "10.0.102.0/24"]
}

variable "node_instance_types" {
  description = "Instance types of the node group"
  type        = list(string)
  default     = ["t4g.large"]
}

variable "node_min_size" {
  description = "Smallest number of nodes"
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = "Largest number of nodes"
  type        = number
  default     = 4
}

variable "node_desired_size" {
  description = "Number of nodes to start with"
  type        = number
  default     = 2
}

variable "image_name_prefix" {
  description = "First part of every ECR repository name"
  type        = string
  default     = "final-project"
}

variable "service_names" {
  description = "Services that have an image, one ECR repository each"
  type        = list(string)
  default     = ["training", "inference", "registry-ops", "drift-monitor"]
}

variable "github_repository" {
  description = "Repository whose workflows may assume the CI role, in the form owner/name"
  type        = string
  default     = "MaksDeGreez/goit-mlops"
}

variable "github_branch" {
  description = "The only branch that may assume the CI role"
  type        = string
  default     = "final-project"
}

variable "state_machine_name" {
  description = "Name of the training state machine, created by the platform stack. Keep it the same in both stacks."
  type        = string
  default     = "mlops-final-training"
}

variable "mlops_engineer_group" {
  description = "Kubernetes group the platform role is mapped to"
  type        = string
  default     = "mlops-engineers"
}

variable "viewer_group" {
  description = "Kubernetes group the read only role is mapped to"
  type        = string
  default     = "viewers"
}
