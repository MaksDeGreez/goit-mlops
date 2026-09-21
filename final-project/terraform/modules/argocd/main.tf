# Argo CD, installed as two Helm releases.
#
#   1. argo-cd      the controller itself
#   2. argocd-apps  the one root Application, the app of apps
#
# They are split because an Application is a custom resource: its CRD only
# exists after the first release is installed.
#
# Terraform stops here. Everything that runs in the cluster is described in
# final-project/gitops/ and is deployed by Argo CD. The only thing that crosses
# the border is a short list of values that Argo CD cannot know by itself,
# above all the ECR registry host, because it contains the account id and must
# never be written into a public repository.

resource "helm_release" "argocd" {
  name       = "argocd"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argo-cd"
  version    = var.chart_version

  namespace = var.namespace
  # The namespace is created by the stack, together with the other namespaces
  # of the project, so all of them are in one place.
  create_namespace = false

  values = [file("${path.module}/values/argocd-values.yaml")]

  # Several images are pulled on a small cluster, so more than the default
  # five minutes is needed.
  timeout = 900
  wait    = true
}

resource "helm_release" "argocd_apps" {
  name       = "argocd-apps"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argocd-apps"
  version    = var.apps_chart_version

  namespace = var.namespace

  values = [
    templatefile("${path.module}/values/root-application.yaml", {
      application_name = var.root_application_name
      argocd_namespace = var.namespace
      repo_url         = var.gitops_repo_url
      target_revision  = var.gitops_revision
      bootstrap_path   = var.bootstrap_path
      image_registry   = var.image_registry
      aws_region       = var.aws_region
      artifact_bucket  = var.mlflow_artifact_bucket
      cluster_name     = var.cluster_name
    })
  ]

  depends_on = [helm_release.argocd]
}
