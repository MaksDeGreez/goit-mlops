variable "name_prefix" {
  description = "First part of every repository name, before the slash"
  type        = string
  default     = "final-project"
}

variable "service_names" {
  description = "Services that have an image. One repository is created for each."
  type        = list(string)
}

variable "keep_last_images" {
  description = "How many images a repository keeps before the oldest are deleted"
  type        = number
  default     = 10
}

variable "tags" {
  description = "Tags added to every resource of the module"
  type        = map(string)
  default     = {}
}
