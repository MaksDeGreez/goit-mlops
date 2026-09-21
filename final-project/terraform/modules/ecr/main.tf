# One ECR repository per service image.
#
# The names carry the prefix of the project, so the repositories are
# "final-project/training", "final-project/inference" and so on, and an image
# is "<account>.dkr.ecr.<region>.amazonaws.com/final-project/training:<tag>".

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  repositories = { for name in var.service_names : name => "${var.name_prefix}/${name}" }

  # The registry host. It contains the account id, which is why it is never
  # written into Git: Terraform injects it into the root Argo CD Application.
  registry_url = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${data.aws_region.current.region}.amazonaws.com"
}

resource "aws_ecr_repository" "this" {
  for_each = local.repositories

  name = each.value

  # A tag always points at the same image. CI tags every image with the git
  # commit, so a rebuild of the same commit is refused instead of quietly
  # changing what a running pod would pull.
  image_tag_mutability = "IMMUTABLE"

  # The whole project is created and destroyed again in every working session.
  # Without this, "terraform destroy" stops on a repository that still holds
  # images.
  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = var.tags
}

# Old images are deleted automatically, so storage stays near zero.
resource "aws_ecr_lifecycle_policy" "this" {
  for_each = aws_ecr_repository.this

  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep only the ${var.keep_last_images} newest images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = var.keep_last_images
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
