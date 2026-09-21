# Module `argocd`

Installs Argo CD and the one root Application that pulls everything else from
Git.

Two Helm releases, because an `Application` is a custom resource and its CRD
only exists after the controller is installed:

| Release | Chart | Version |
|---|---|---|
| `argocd` | `argo-cd` | 10.9.2 (Argo CD 3.5.3) |
| `argocd-apps` | `argocd-apps` | 2.0.5 |

`values/argocd-values.yaml` keeps the controller small: Dex off, notifications
off, ClusterIP service, `--insecure` (the UI is opened with port-forward),
60 second reconciliation, and the Lua health check for `Application` objects
that makes sync waves work between Applications.

`values/root-application.yaml` is a Terraform template. It writes the root
Application and hands it the six values Argo CD cannot read from Git:

| Value | Where it comes from |
|---|---|
| `repoURL`, `targetRevision` | variables of the stack |
| `imageRegistry` | `module.ecr.registry_url` — holds the account id, never in Git |
| `awsRegion` | variable of the stack |
| `mlflowArtifactBucket` | `module.mlflow` — the name has a random suffix |
| `clusterName` | the infra stack |

The root Application carries the Argo CD finalizer, so deleting it removes
everything it created. That is the first step of the teardown.
