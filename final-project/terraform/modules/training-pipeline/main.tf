# The training pipeline.
#
#   ValidateInput  -> a Lambda that checks the input and builds the job
#   RunTrainingJob -> a Kubernetes Job in the cluster, run and waited for by
#                     arn:aws:states:::eks:runJob.sync
#   LogMetrics     -> a Lambda that reads the logs of that job and records the
#                     result of the training run
#
# Any failure jumps to a Fail state, so an execution is either green with a new
# model version or red with the reason in its history.
#
# The Job runs in the cluster and not in a Lambda because training needs about
# a gigabyte of memory, the whole scikit-learn stack and access to MLflow over
# the cluster network. Step Functions starts it, waits for it and brings its
# logs back, which is exactly what the assignment asks a pipeline to do.

locals {
  validate_function_name    = "${var.name_prefix}-validate-input"
  log_metrics_function_name = "${var.name_prefix}-log-metrics"
  state_machine_name        = var.state_machine_name
  build_dir                 = "${path.module}/build"
}

# ---------------------------------------------------------------------------
# Deployment packages
# ---------------------------------------------------------------------------

# Both functions use the standard library only, so each package is one file and
# there is nothing to build. The .zip files land in a directory that is not
# committed; the source is in final-project/lambda/.
data "archive_file" "validate_input" {
  type        = "zip"
  source_file = "${var.lambda_source_dir}/validate_input.py"
  output_path = "${local.build_dir}/validate_input.zip"
}

data "archive_file" "log_metrics" {
  type        = "zip"
  source_file = "${var.lambda_source_dir}/log_metrics.py"
  output_path = "${local.build_dir}/log_metrics.zip"
}

# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

# The log groups are created here instead of being created by Lambda itself, so
# the retention is set from the start and old logs disappear on their own.
resource "aws_cloudwatch_log_group" "validate_input" {
  name              = "/aws/lambda/${local.validate_function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "log_metrics" {
  name              = "/aws/lambda/${local.log_metrics_function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# Step Functions only writes to log groups whose name starts like this.
resource "aws_cloudwatch_log_group" "state_machine" {
  name              = "/aws/vendedlogs/states/${local.state_machine_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# ---------------------------------------------------------------------------
# Lambda functions
# ---------------------------------------------------------------------------

resource "aws_iam_role" "lambda" {
  name               = "${var.name_prefix}-pipeline-lambda"
  description        = "Used by the two Lambda functions of the training pipeline"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = var.tags
}

# Writing its own logs is the only thing either function does besides returning
# a value. There is no VPC access, no S3, no Kubernetes.
resource "aws_iam_role_policy" "lambda_logging" {
  name   = "write-own-logs"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda_logging.json
}

resource "aws_lambda_function" "validate_input" {
  function_name = local.validate_function_name
  description   = "Step 1: check the pipeline input and build the training job"
  role          = aws_iam_role.lambda.arn

  filename = data.archive_file.validate_input.output_path
  handler  = "validate_input.lambda_handler"
  runtime  = var.lambda_runtime

  # Without this Terraform does not notice that the code inside the archive
  # changed and does not upload the new version.
  source_code_hash = data.archive_file.validate_input.output_base64sha256

  architectures = [var.lambda_architecture]
  memory_size   = var.lambda_memory_mb
  timeout       = var.lambda_timeout_seconds

  environment {
    variables = {
      TRAINING_IMAGE_REPOSITORY = var.training_image_repository
      JOB_NAME_PREFIX           = var.job_name_prefix
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.validate_input,
    aws_iam_role_policy.lambda_logging,
  ]

  tags = var.tags
}

resource "aws_lambda_function" "log_metrics" {
  function_name = local.log_metrics_function_name
  description   = "Step 3: read the result of the training job out of its logs"
  role          = aws_iam_role.lambda.arn

  filename         = data.archive_file.log_metrics.output_path
  handler          = "log_metrics.lambda_handler"
  runtime          = var.lambda_runtime
  source_code_hash = data.archive_file.log_metrics.output_base64sha256

  architectures = [var.lambda_architecture]
  memory_size   = var.lambda_memory_mb
  timeout       = var.lambda_timeout_seconds

  environment {
    variables = {
      # Only used to put the address into the log line, so a reader knows which
      # MLflow holds the run.
      MLFLOW_TRACKING_URI = var.mlflow_tracking_uri
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.log_metrics,
    aws_iam_role_policy.lambda_logging,
  ]

  tags = var.tags
}

# ---------------------------------------------------------------------------
# The role of the state machine
# ---------------------------------------------------------------------------

resource "aws_iam_role" "state_machine" {
  name               = "${var.name_prefix}-training-pipeline"
  description        = "Used by the training state machine to call Lambda and to run a Job in the cluster"
  assume_role_policy = data.aws_iam_policy_document.state_machine_assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "state_machine" {
  name   = "run-the-training-pipeline"
  role   = aws_iam_role.state_machine.id
  policy = data.aws_iam_policy_document.state_machine.json
}

# IAM only gets the state machine as far as the Kubernetes API. What it may do
# once it is there is decided by this access entry and by the Role and
# RoleBinding for the group in final-project/rbac/: create and read Jobs in
# mlops-system, and read pods and their logs, which RetrieveLogs needs.
resource "aws_eks_access_entry" "state_machine" {
  cluster_name      = var.cluster_name
  principal_arn     = aws_iam_role.state_machine.arn
  kubernetes_groups = [var.kubernetes_group]
  type              = "STANDARD"

  tags = var.tags
}

# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------

resource "aws_sfn_state_machine" "training" {
  name     = local.state_machine_name
  role_arn = aws_iam_role.state_machine.arn
  type     = "STANDARD"

  definition = local.definition

  logging_configuration {
    log_destination = "${aws_cloudwatch_log_group.state_machine.arn}:*"
    level           = "ALL"
    # The execution data holds the retrieved pod logs. They are already in the
    # execution history in the console, so copying them into CloudWatch as well
    # would only cost money.
    include_execution_data = false
  }

  tags = var.tags

  depends_on = [
    aws_iam_role_policy.state_machine,
    aws_eks_access_entry.state_machine,
  ]
}
