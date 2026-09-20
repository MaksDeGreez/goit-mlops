# Stack 2 of 2: what has to exist inside the cluster before Argo CD can do its
# job, plus the training pipeline. Apply this one after "infra".
#
# The split of work is the same everywhere:
#
#   Terraform owns AWS resources, the namespaces and the generated passwords;
#   Argo CD owns every Helm chart and every manifest.
#
# That is why there are exactly two secrets and five namespaces here and no
# workloads at all.

locals {
  tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
    Stack     = "platform"
  }

  cluster_name = data.terraform_remote_state.infra.outputs.cluster_name
}

# Namespaces are created here and not by Argo CD, so the two secrets below can
# be written before any chart is synced, and so the Applications can use
# CreateNamespace=false.
resource "kubernetes_namespace_v1" "this" {
  for_each = toset(var.namespaces)

  metadata {
    name = each.value

    labels = {
      "app.kubernetes.io/part-of"    = var.project_name
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }
}

module "mlflow" {
  source = "../../modules/mlflow"

  name_prefix  = var.project_name
  cluster_name = local.cluster_name
  namespace    = var.mlops_namespace

  tags = local.tags

  depends_on = [kubernetes_namespace_v1.this]
}

module "monitoring" {
  source = "../../modules/monitoring"

  name_prefix = var.project_name
  namespace   = var.monitoring_namespace

  depends_on = [kubernetes_namespace_v1.this]
}

module "training_pipeline" {
  source = "../../modules/training-pipeline"

  name_prefix        = var.project_name
  state_machine_name = var.state_machine_name

  # final-project/lambda/, three levels up from this stack.
  lambda_source_dir = "${path.root}/../../../lambda"

  cluster_name                       = local.cluster_name
  cluster_endpoint                   = data.terraform_remote_state.infra.outputs.cluster_endpoint
  cluster_certificate_authority_data = data.terraform_remote_state.infra.outputs.cluster_certificate_authority_data
  namespace                          = var.mlops_namespace

  training_image_repository = data.terraform_remote_state.infra.outputs.ecr_repository_urls["training"]
  mlflow_tracking_uri       = var.mlflow_tracking_uri
  model_name                = var.model_name

  tags = local.tags
}

# Argo CD comes last, because the root Application is handed the name of the
# MLflow bucket, and that name is only known after the bucket exists.
module "argocd" {
  source = "../../modules/argocd"

  namespace       = var.argocd_namespace
  gitops_repo_url = var.gitops_repo_url
  gitops_revision = var.gitops_revision
  bootstrap_path  = var.bootstrap_path

  image_registry         = data.terraform_remote_state.infra.outputs.ecr_registry_url
  aws_region             = var.aws_region
  mlflow_artifact_bucket = module.mlflow.artifact_bucket
  cluster_name           = local.cluster_name

  depends_on = [kubernetes_namespace_v1.this]
}
