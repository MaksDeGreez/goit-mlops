variable "name" {
  description = "Short name used as a prefix for the network resources"
  type        = string
}

variable "cidr" {
  description = "CIDR block of the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "azs" {
  description = "Availability zones to spread the subnets over. EKS needs at least two."
  type        = list(string)
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks of the private subnets, one per availability zone"
  type        = list(string)
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks of the public subnets, one per availability zone"
  type        = list(string)
}

variable "tags" {
  description = "Tags added to every resource of the module"
  type        = map(string)
  default     = {}
}
