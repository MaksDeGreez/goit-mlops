# Training pipeline: a Step Functions state machine that calls two Lambda
# functions one after another, ValidateData and LogMetrics.

locals {
  validate_function_name    = "${var.project_name}-validate"
  log_metrics_function_name = "${var.project_name}-log-metrics"
  lambda_source_dir         = "${path.module}/lambda"
}

# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

# The log groups are created here instead of letting Lambda create them, so
# that the retention period is set from the start and old logs are deleted
# automatically.
resource "aws_cloudwatch_log_group" "validate" {
  name              = "/aws/lambda/${local.validate_function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "log_metrics" {
  name              = "/aws/lambda/${local.log_metrics_function_name}"
  retention_in_days = var.log_retention_days
}

# ---------------------------------------------------------------------------
# IAM role for the Lambda functions
# ---------------------------------------------------------------------------

resource "aws_iam_role" "lambda_exec" {
  name               = "${var.project_name}-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy" "lambda_logging" {
  name   = "${var.project_name}-lambda-logging"
  role   = aws_iam_role.lambda_exec.id
  policy = data.aws_iam_policy_document.lambda_logging.json
}

# ---------------------------------------------------------------------------
# Lambda functions
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "validate" {
  function_name = local.validate_function_name
  description   = "Step 1 of the training pipeline: check the input data"
  role          = aws_iam_role.lambda_exec.arn

  filename = "${local.lambda_source_dir}/validate.zip"
  handler  = "validate.lambda_handler"
  runtime  = var.lambda_runtime

  # Without this hash Terraform does not notice that the code inside the
  # archive has changed and does not upload the new version.
  source_code_hash = filebase64sha256("${local.lambda_source_dir}/validate.zip")

  architectures = [var.lambda_architecture]
  memory_size   = var.lambda_memory_mb
  timeout       = var.lambda_timeout_seconds

  depends_on = [
    aws_cloudwatch_log_group.validate,
    aws_iam_role_policy.lambda_logging,
  ]
}

resource "aws_lambda_function" "log_metrics" {
  function_name = local.log_metrics_function_name
  description   = "Step 2 of the training pipeline: log the metrics of the run"
  role          = aws_iam_role.lambda_exec.arn

  filename         = "${local.lambda_source_dir}/log_metrics.zip"
  handler          = "log_metrics.lambda_handler"
  runtime          = var.lambda_runtime
  source_code_hash = filebase64sha256("${local.lambda_source_dir}/log_metrics.zip")

  architectures = [var.lambda_architecture]
  memory_size   = var.lambda_memory_mb
  timeout       = var.lambda_timeout_seconds

  depends_on = [
    aws_cloudwatch_log_group.log_metrics,
    aws_iam_role_policy.lambda_logging,
  ]
}

# ---------------------------------------------------------------------------
# IAM role for the state machine
# ---------------------------------------------------------------------------

resource "aws_iam_role" "step_functions" {
  name               = "${var.project_name}-step-functions-role"
  assume_role_policy = data.aws_iam_policy_document.step_functions_assume_role.json
}

resource "aws_iam_role_policy" "step_functions_invoke_lambda" {
  name   = "${var.project_name}-invoke-lambda"
  role   = aws_iam_role.step_functions.id
  policy = data.aws_iam_policy_document.step_functions_invoke_lambda.json
}

# ---------------------------------------------------------------------------
# Step Functions state machine
# ---------------------------------------------------------------------------

resource "aws_sfn_state_machine" "train_pipeline" {
  name     = "${var.project_name}-pipeline"
  role_arn = aws_iam_role.step_functions.arn

  definition = jsonencode({
    Comment = "Training pipeline: validate the data, then log the metrics"
    StartAt = "ValidateData"

    States = {
      # The output of this state is passed as the input of the next one.
      ValidateData = {
        Type     = "Task"
        Resource = aws_lambda_function.validate.arn
        Comment  = "Check that the workflow received the required fields"
        Retry = [
          {
            # Retry only on temporary AWS errors, never on a failed validation.
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.TooManyRequestsException"]
            IntervalSeconds = 2
            MaxAttempts     = 2
            BackoffRate     = 2
          }
        ]
        Next = "LogMetrics"
      }

      LogMetrics = {
        Type     = "Task"
        Resource = aws_lambda_function.log_metrics.arn
        Comment  = "Write the metrics of the run to the logs"
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.TooManyRequestsException"]
            IntervalSeconds = 2
            MaxAttempts     = 2
            BackoffRate     = 2
          }
        ]
        End = true
      }
    }
  })
}
