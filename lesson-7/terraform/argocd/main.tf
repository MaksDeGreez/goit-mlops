# Argo CD is installed as a Helm release, so the whole GitOps controller is
# described in code. Two releases are used:
#
#   1. argo-cd      — the controller itself, configured by values/argocd-values.yaml
#   2. argocd-apps  — the ApplicationSet object, configured by values/argocd-apps-values.yaml
#
# They are split because the ApplicationSet is a custom resource. Its CRD only
# exists after the first release is installed, so the second release has to run
# after the first one.

resource "helm_release" "argocd" {
  name       = "argocd"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argo-cd"
  version    = var.argocd_chart_version

  namespace        = var.namespace
  create_namespace = true

  values = [file("${path.module}/values/argocd-values.yaml")]

  # The cluster pulls several images, so give it more than the default 5 minutes.
  timeout = 900
  wait    = true
}

resource "helm_release" "argocd_apps" {
  name       = "argocd-apps"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argocd-apps"
  version    = var.argocd_apps_chart_version

  namespace = var.namespace

  values = [
    templatefile("${path.module}/values/argocd-apps-values.yaml", {
      namespace = var.namespace
      repo_url  = var.gitops_repo_url
      revision  = var.gitops_repo_revision
    })
  ]

  depends_on = [helm_release.argocd]
}

# The chart writes the first admin password into this secret. It is read here
# only to print it as an output, so the UI can be opened without extra steps.
data "kubernetes_secret" "argocd_admin" {
  metadata {
    name      = "argocd-initial-admin-secret"
    namespace = var.namespace
  }

  depends_on = [helm_release.argocd]
}
