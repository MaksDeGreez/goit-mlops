# Information about the current account and region.
data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

# Which service is allowed to use the Lambda role.
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

# What the Lambda functions are allowed to do: write their own logs, nothing else.
data "aws_iam_policy_document" "lambda_logging" {
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "${aws_cloudwatch_log_group.validate.arn}:*",
      "${aws_cloudwatch_log_group.log_metrics.arn}:*",
    ]
  }
}

# Which service is allowed to use the Step Functions role.
data "aws_iam_policy_document" "step_functions_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

# The state machine may call exactly these two functions and nothing else.
data "aws_iam_policy_document" "step_functions_invoke_lambda" {
  statement {
    effect  = "Allow"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.validate.arn,
      aws_lambda_function.log_metrics.arn,
    ]
  }
}
