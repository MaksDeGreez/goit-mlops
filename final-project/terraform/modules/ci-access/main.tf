# Access for GitHub Actions without long lived keys.
#
# GitHub gives every workflow run a short lived token. AWS is configured to
# trust that token, so the pipeline assumes a role for a few minutes instead of
# storing an access key. The repository is public, so no secret may be stored
# in it at all.

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

locals {
  repo_owner = split("/", var.github_repository)[0]
  repo_name  = split("/", var.github_repository)[1]

  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.region
  partition  = data.aws_partition.current.partition

  # Built from the name instead of read from the platform stack. The state
  # machine is created later, in the platform stack, and that stack reads this
  # one. Referring to it the other way round would be a cycle between stacks.
  state_machine_arn = "arn:${local.partition}:states:${local.region}:${local.account_id}:stateMachine:${var.state_machine_name}"
  execution_arn     = "arn:${local.partition}:states:${local.region}:${local.account_id}:execution:${var.state_machine_name}:*"
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]

  # GitHub rotates these; AWS ignores the list for this provider since 2023 but
  # the argument is still required.
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]

  tags = var.tags
}

data "aws_iam_policy_document" "assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # GitHub describes this claim as "repo:owner/name:ref:refs/heads/branch",
    # but it also sends a longer form with the numeric ids of the owner and of
    # the repository:
    #   repo:owner@178340907/name@1359527131:ref:refs/heads/final-project
    # A StringEquals condition therefore never matches. Both shapes are
    # accepted here with StringLike. The branch is still fixed, so only this
    # branch of this repository can use the role.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${var.github_repository}:ref:refs/heads/${var.github_branch}",
        "repo:${local.repo_owner}@*/${local.repo_name}@*:ref:refs/heads/${var.github_branch}",
      ]
    }
  }
}

data "aws_iam_policy_document" "permissions" {
  # Getting a registry login token is an account wide call: it has no resource
  # of its own, so "*" is the only value AWS accepts here.
  statement {
    sid       = "EcrLogin"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  # Pushing and reading images, but only in the four repositories of this
  # project. Deleting images is not allowed: the lifecycle rule does that.
  statement {
    sid    = "EcrPush"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:DescribeRepositories",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = var.ecr_repository_arns
  }

  # Starting the training pipeline and waiting for its result.
  statement {
    sid       = "StartTrainingPipeline"
    effect    = "Allow"
    actions   = ["states:StartExecution"]
    resources = [local.state_machine_arn]
  }

  statement {
    sid    = "ReadItsOwnExecution"
    effect = "Allow"
    actions = [
      "states:DescribeExecution",
      "states:GetExecutionHistory",
    ]
    resources = [local.execution_arn]
  }
}

resource "aws_iam_role" "ci" {
  name                 = "${var.name_prefix}-github-actions"
  description          = "Assumed by GitHub Actions on branch ${var.github_branch} to push images and start training"
  assume_role_policy   = data.aws_iam_policy_document.assume_role.json
  max_session_duration = 3600
  tags                 = var.tags
}

resource "aws_iam_role_policy" "ci" {
  name   = "push-images-and-start-training"
  role   = aws_iam_role.ci.id
  policy = data.aws_iam_policy_document.permissions.json
}
