output "artifact_bucket" {
  description = "Name of the S3 bucket MLflow stores its artifacts in"
  value       = aws_s3_bucket.artifacts.bucket
}

output "artifact_bucket_arn" {
  description = "ARN of the artifact bucket"
  value       = aws_s3_bucket.artifacts.arn
}

output "role_arn" {
  description = "IAM role the MLflow service account uses through Pod Identity"
  value       = aws_iam_role.mlflow.arn
}

output "postgres_secret_name" {
  description = "Kubernetes secret with the keys username, password and database"
  value       = kubernetes_secret_v1.postgres.metadata[0].name
}

output "postgres_database" {
  description = "Name of the database MLflow uses"
  value       = var.postgres_database
}
