# Module `mlflow`

Everything MLflow needs that Argo CD cannot create itself.

* **S3 bucket** for the model artifacts: versioning on, AES256 encryption,
  public access blocked, a bucket policy that denies anything that is not TLS,
  `force_destroy = true`. The name gets a random suffix, because bucket names
  are global and the account id may not be published.
* **IAM role** with access to that one bucket only, plus an
  `aws_eks_pod_identity_association` for the service account `mlflow` in
  `mlops-system`. No access keys anywhere. The service account object itself is
  a plain manifest in `final-project/rbac/`.
* **Secret `mlflow-postgres`** in `mlops-system` with the keys `username`,
  `password` and `database`. The password is a `random_password`; the charts
  read it with `existingSecret`, so it is never in Git or in a values file. It
  is in the Terraform state, which is why the state bucket is private and
  encrypted.

The MLflow server, its Postgres and the ArgoCD Application that deploys them
are in `final-project/gitops/`.
