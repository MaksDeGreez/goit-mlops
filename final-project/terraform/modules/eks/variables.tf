variable "cluster_name" {
  description = "Name of the EKS cluster"
  type        = string
}

variable "kubernetes_version" {
  description = "Kubernetes version of the control plane"
  type        = string
}

variable "region" {
  description = "AWS region the cluster runs in"
  type        = string
}

variable "vpc_id" {
  description = "VPC the cluster is created in"
  type        = string
}

variable "subnet_ids" {
  description = "Private subnets for the control plane network interfaces and for the nodes"
  type        = list(string)
}

variable "instance_types" {
  description = "Instance types of the node group. Graviton (arm64), same architecture as the images."
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

variable "node_disk_size" {
  description = "Size of the root volume of a node in GiB. The container images of this project are large."
  type        = number
  default     = 50
}

variable "log_retention_days" {
  description = "How long CloudWatch keeps the control plane logs"
  type        = number
  default     = 7
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

variable "tags" {
  description = "Tags added to every resource of the module"
  type        = map(string)
  default     = {}
}
