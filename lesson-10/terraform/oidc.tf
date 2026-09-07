# Access for GitHub Actions without long lived keys.
#
# GitHub gives every workflow run a short lived token. AWS is configured to
# trust that token, so the pipeline can assume a role for a few minutes instead
# of storing an access key in the repository. The repository is public, so no
# secret may be stored in it.

locals {
  repo_owner = split("/", var.github_repository)[0]
  repo_name  = split("/", var.github_repository)[1]
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]
}

# Only a workflow that runs in this repository and on this branch may use the role.
data "aws_iam_policy_document" "github_actions_assume_role" {
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

    # GitHub describes this claim as "repo:owner/name:ref:refs/heads/branch", but
    # it now also sends a longer form that includes the numeric id of the owner
    # and of the repository, for example:
    #   repo:owner@178340907/name@1359527131:ref:refs/heads/lesson-10
    # Both forms are accepted here, so the role keeps working either way. The
    # branch is still fixed, so only this branch of this repository can use it.
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

# The pipeline may start the state machine and read the result of its own run.
# It cannot create, change or delete anything.
data "aws_iam_policy_document" "github_actions_permissions" {
  statement {
    effect    = "Allow"
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.train_pipeline.arn]
  }

  statement {
    effect = "Allow"
    actions = [
      "states:DescribeExecution",
      "states:GetExecutionHistory",
    ]
    resources = [
      "arn:aws:states:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:execution:${aws_sfn_state_machine.train_pipeline.name}:*",
    ]
  }
}

resource "aws_iam_role" "github_actions" {
  name                 = "${var.project_name}-github-actions-role"
  description          = "Assumed by GitHub Actions to start the training pipeline"
  assume_role_policy   = data.aws_iam_policy_document.github_actions_assume_role.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy" "github_actions" {
  name   = "${var.project_name}-start-execution"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_actions_permissions.json
}
