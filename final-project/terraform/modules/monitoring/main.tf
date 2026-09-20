# The only thing the monitoring stack needs from Terraform is the Grafana admin
# password. Everything else - Prometheus, Grafana, Loki, Alloy, PushGateway,
# OpenCost - is a Helm chart deployed by Argo CD.
#
# The password is generated here and written into a Kubernetes secret, and the
# Grafana chart reads it with admin.existingSecret. That way it is never in Git
# and never in a values file.

resource "random_password" "grafana_admin" {
  length = 24
  # Grafana is logged into through a browser, so the password only has to be
  # easy to copy. These characters need no quoting in a shell either.
  special          = true
  override_special = "-_"
}

resource "kubernetes_secret_v1" "grafana_admin" {
  metadata {
    name      = var.grafana_secret_name
    namespace = var.namespace

    labels = {
      "app.kubernetes.io/name"    = "grafana"
      "app.kubernetes.io/part-of" = var.name_prefix
    }
  }

  # The key names are the ones the Grafana chart expects under
  # admin.userKey and admin.passwordKey.
  data = {
    "admin-user"     = var.grafana_admin_user
    "admin-password" = random_password.grafana_admin.result
  }

  type = "Opaque"
}
