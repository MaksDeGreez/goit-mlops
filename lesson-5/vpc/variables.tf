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

variable "vpc_cidr" {
  description = "CIDR block of the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "azs" {
  description = "Availability zones to spread the subnets over. EKS needs at least two."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks of the private subnets, one per availability zone"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks of the public subnets, one per availability zone"
  type        = list(string)
  default     = ["10.0.101.0/24", "10.0.102.0/24"]
}
