data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  cluster_arn = "arn:${data.aws_partition.current.partition}:eks:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:cluster/${var.cluster_name}"
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "lambda_logging" {
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "${aws_cloudwatch_log_group.validate_input.arn}:*",
      "${aws_cloudwatch_log_group.log_metrics.arn}:*",
    ]
  }
}

data "aws_iam_policy_document" "state_machine_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "state_machine" {
  # Exactly these two functions and nothing else.
  statement {
    sid     = "CallTheTwoFunctions"
    effect  = "Allow"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.validate_input.arn,
      aws_lambda_function.log_metrics.arn,
    ]
  }

  # eks:runJob talks to the Kubernetes API itself, so it has to look the
  # cluster up first. This is the only EKS permission it needs: what it may do
  # inside the cluster comes from the access entry, not from IAM.
  statement {
    sid       = "FindTheCluster"
    effect    = "Allow"
    actions   = ["eks:DescribeCluster"]
    resources = [local.cluster_arn]
  }

  # Step Functions logging. These calls are account wide and AWS rejects the
  # policy if a resource is given, so "*" is the only value that works here.
  # The log group itself is created by Terraform with a short retention.
  statement {
    sid    = "WriteExecutionLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }
}
