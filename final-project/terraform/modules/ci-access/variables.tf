variable "name_prefix" {
  description = "First part of the name of the IAM role"
  type        = string
}

variable "github_repository" {
  description = "Repository allowed to assume the role, in the form owner/name"
  type        = string
}

variable "github_branch" {
  description = "The only branch that may assume the role"
  type        = string
}

variable "ecr_repository_arns" {
  description = "ARNs of the ECR repositories CI may push to"
  type        = list(string)
}

variable "state_machine_name" {
  description = "Name of the training state machine. The ARN is built from it, see the comment in main.tf."
  type        = string
}

variable "tags" {
  description = "Tags added to every resource of the module"
  type        = map(string)
  default     = {}
}
