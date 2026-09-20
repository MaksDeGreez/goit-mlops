# What MLflow needs from AWS and from Terraform:
#
#   * an S3 bucket for the model artifacts;
#   * an IAM role the MLflow pod uses through EKS Pod Identity, so there are no
#     access keys anywhere;
#   * the Postgres password, generated here and written into a Kubernetes
#     secret. The chart and the Postgres manifests read that secret, so the
#     password is never in Git and never in a values file.
#
# The MLflow server itself is a Helm chart deployed by Argo CD, not by
# Terraform.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

# A bucket name has to be unique in the whole of AWS, and the account id may
# not be published, so a random suffix is used instead.
resource "random_string" "bucket_suffix" {
  length  = 6
  lower   = true
  upper   = false
  numeric = true
  special = false
}

resource "aws_s3_bucket" "artifacts" {
  bucket = "${var.bucket_prefix}-${random_string.bucket_suffix.result}"

  # The project is created and destroyed again in every working session, and
  # the artifacts are rebuilt by the next training run. Without this a destroy
  # stops on a bucket that still holds objects.
  force_destroy = true

  tags = var.tags
}

# Versioning is part of the answer to "is this still the model that was
# trained?": the checksum tells you the file changed, the version history tells
# you what it was before.
resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Refuse anything that does not arrive over TLS. The public access block
# already stops anonymous reads; this also covers a signed request made over
# plain HTTP.
data "aws_iam_policy_document" "bucket" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.artifacts.arn,
      "${aws_s3_bucket.artifacts.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  policy = data.aws_iam_policy_document.bucket.json

  # The policy denies everything that is not TLS, including the call that
  # writes the public access block, so the order matters.
  depends_on = [aws_s3_bucket_public_access_block.artifacts]
}

# ---------------------------------------------------------------------------
# The role the MLflow pod uses
# ---------------------------------------------------------------------------

# EKS Pod Identity: the pods service assumes the role on behalf of the service
# account. sts:TagSession is required, the association fails without it.
data "aws_iam_policy_document" "assume_role" {
  statement {
    effect = "Allow"
    actions = [
      "sts:AssumeRole",
      "sts:TagSession",
    ]

    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

# Only this one bucket, and only the actions MLflow really makes.
data "aws_iam_policy_document" "artifacts_access" {
  statement {
    sid       = "ListTheBucket"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.artifacts.arn]
  }

  statement {
    sid    = "ReadAndWriteArtifacts"
    effect = "Allow"
    actions = [
      "s3:AbortMultipartUpload",
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:ListMultipartUploadParts",
      "s3:PutObject",
    ]
    resources = ["${aws_s3_bucket.artifacts.arn}/*"]
  }
}

resource "aws_iam_role" "mlflow" {
  name               = "${var.name_prefix}-mlflow"
  description        = "Used by the MLflow server pod to read and write its artifact bucket"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "mlflow" {
  name   = "artifact-bucket-access"
  role   = aws_iam_role.mlflow.id
  policy = data.aws_iam_policy_document.artifacts_access.json
}

# The service account itself is a plain manifest in final-project/rbac/ and is
# created by Argo CD. This only says which role that service account may use.
resource "aws_eks_pod_identity_association" "mlflow" {
  cluster_name    = var.cluster_name
  namespace       = var.namespace
  service_account = var.service_account
  role_arn        = aws_iam_role.mlflow.arn

  tags = var.tags
}

# ---------------------------------------------------------------------------
# The Postgres password
# ---------------------------------------------------------------------------

# Generated on every apply and never printed. The charts read it with
# existingSecret, so it is not in Git and not in any values file. It does end
# up in the Terraform state, which is why the state bucket is private and
# encrypted.
resource "random_password" "postgres" {
  length = 32
  # Kubernetes, Postgres and the MLflow connection string all handle these
  # characters without quoting.
  special          = true
  override_special = "-_"
}

resource "kubernetes_secret_v1" "postgres" {
  metadata {
    name      = var.postgres_secret_name
    namespace = var.namespace

    labels = {
      "app.kubernetes.io/name"    = "mlflow"
      "app.kubernetes.io/part-of" = var.name_prefix
    }
  }

  data = {
    username = var.postgres_username
    password = random_password.postgres.result
    database = var.postgres_database
  }

  type = "Opaque"
}
