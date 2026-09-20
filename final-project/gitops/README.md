# GitOps

Everything that runs in the cluster is described here. Terraform builds the AWS
side (VPC, EKS, ECR, S3, the secrets) and installs Argo CD; from that point on
Argo CD reads this folder and nothing is installed by hand.

## How it fits together

Terraform creates one Argo CD Application, the **root**. It points at
`gitops/bootstrap`, which is a small Helm chart whose only output is one
`Application` object per component. That is the "app of apps" pattern: one
thing to create, and everything else follows.

```
Terraform
  └── root Application  ->  final-project/gitops/bootstrap   (this chart)
        ├── rbac, argo-rollouts, postgres                    wave 0
        ├── mlflow, prometheus, pushgateway, loki            wave 1
        ├── alloy, grafana, grafana-dashboards, opencost     wave 2
        └── inference-staging, inference-production,         wave 3
            drift-monitor
```

A **sync wave** is the order Argo CD works in: it finishes wave 0 and waits
until those Applications are healthy before it starts wave 1. That is why
PostgreSQL is running before MLflow tries to connect, and why the Argo Rollouts
CustomResourceDefinitions exist before the first `Rollout` object is applied.

Terraform passes six values into the root Application:

| Value | Why it is not in Git |
|---|---|
| `repoURL`, `targetRevision` | so a fork or a branch can be tested without editing files |
| `imageRegistry` | it contains the AWS account id |
| `awsRegion`, `mlflowArtifactBucket`, `clusterName` | only known once Terraform has created them |

`values.yaml` holds a readable placeholder for each of them, so
`helm template` works without Terraform.

## Components

| Application | What it is | Chart | Version | Namespace | Wave | CPU / memory requested | Disk |
|---|---|---|---|---|---|---|---|
| `rbac` | roles, bindings, service accounts | plain manifests | - | own | 0 | - | - |
| `argo-rollouts` | canary controller | `argo/argo-rollouts` | 2.43.2 | `mlops-system` | 0 | 50m / 128Mi | - |
| `postgres` | MLflow backend store | plain manifests | `postgres:17.11-alpine3.24` | `mlops-system` | 0 | 100m / 256Mi | 5Gi |
| `mlflow` | tracking server and model registry | `community-charts/mlflow` | 1.11.7 | `mlops-system` | 1 | 200m / 1Gi | - (S3) |
| `prometheus` | metrics | `prometheus-community/prometheus` | 29.31.1 | `monitoring` | 1 | 270m / 928Mi | 8Gi |
| `pushgateway` | metrics from short jobs | `prometheus-community/prometheus-pushgateway` | 3.8.0 | `monitoring` | 1 | 10m / 32Mi | - |
| `loki` | logs | `grafana-community/loki` | 18.13.4 | `monitoring` | 1 | 100m / 512Mi | 5Gi |
| `alloy` | log collector, one pod per node | `grafana/alloy` | 1.12.1 | `monitoring` | 2 | 120m / 320Mi | - |
| `grafana` | dashboards and alerts | `grafana-community/grafana` | 13.2.5 | `monitoring` | 2 | 60m / 320Mi | - |
| `grafana-dashboards` | three dashboards as ConfigMaps | kustomize | - | `monitoring` | 2 | - | - |
| `opencost` | cost metrics | `opencost/opencost` | 2.5.31 | `monitoring` | 2 | 20m / 128Mi | - |
| `inference-staging` | prediction service, follows the alias | own chart | - | `staging` | 3 | see `envs/staging.yaml` | - |
| `inference-production` | prediction service, pinned version | own chart | - | `production` | 3 | see `envs/production.yaml` | - |
| `drift-monitor` | drift CronJob, every 15 minutes | own chart | - | `mlops-system` | 3 | see the chart | - |

The Prometheus row counts the whole chart: the server, kube-state-metrics and
node-exporter on both nodes.

The numbers were read out of the rendered manifests by
`scripts/validate_gitops.sh`, not estimated. Added up per namespace:

| Namespace | CPU requests | Memory requests | Pods |
|---|---|---|---|
| `argocd` | 250m | 896Mi | 5 |
| `mlops-system` | 350m | 1408Mi | 3 |
| `monitoring` | 580m | 2240Mi | 10 |
| `staging` | 100m | 512Mi | 2 |
| `production` | 500m | 2560Mi | 10 |
| short lived: drift job, registry hook, canary surge pod | up to 350m | up to 704Mi | up to 3 |

The two `t4g.large` nodes have 4 CPUs and 16 GiB in total, of which about
**3.8 CPUs and 12 GiB** can be given to pods. `kube-system` takes roughly
another 0.7 CPU for the EKS add-ons. That leaves headroom, which it has to:
during a canary production runs an eleventh pod.

This is why the inference CPU request is `50m` in both `envs/` files and not
the `100m` of the chart default. At `100m` the two inference namespaces alone
would ask for 1.3 CPU, a third of the cluster, for pods that answer in about
5 ms.

## Addresses other parts depend on

| Address | Used by |
|---|---|
| `mlflow.mlops-system.svc.cluster.local:5000` | training, inference, registry-ops |
| `postgres.mlops-system.svc.cluster.local:5432` | MLflow |
| `prometheus-server.monitoring.svc.cluster.local:80` | Grafana, Argo Rollouts analysis, OpenCost |
| `pushgateway.monitoring.svc.cluster.local:9091` | drift-monitor |
| `loki.monitoring.svc.cluster.local:3100` | Alloy, Grafana, drift-monitor |
| `grafana.monitoring.svc.cluster.local:80` | people, through a port-forward |
| `opencost.monitoring.svc.cluster.local:9003` | Prometheus |

Nothing is public. Everything is reached with `kubectl port-forward`.

## The folders

```
bootstrap/            the app-of-apps chart: one Application per component
apps/<name>/          the values file of a third party chart, or plain manifests
apps/grafana-dashboards/   dashboard JSON plus a kustomization
charts/inference/     our chart: Rollout, Services, analysis, registry hook
charts/drift-monitor/ our chart: the CronJob
envs/                 staging.yaml and production.yaml, the files edited day to day
```

Third party charts are used through **multi-source Applications**: the first
source is the chart in its own Helm repository, the second is this repository
with `ref: values`, which lets the first source read
`$values/final-project/gitops/apps/<name>/values.yaml`. The chart is never
copied into this repository and the version stays visible in the Argo CD UI.

## Running it locally

No cluster is needed for any of this.

```bash
# the Application objects
helm lint  final-project/gitops/bootstrap
helm template bootstrap final-project/gitops/bootstrap -n argocd

# one third party chart with its values, for example Loki
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm template loki grafana-community/loki --version 18.13.4 -n monitoring \
  -f final-project/gitops/apps/loki/values.yaml

# the dashboards
kubectl kustomize final-project/gitops/apps/grafana-dashboards

# schema check of anything rendered above
helm template bootstrap final-project/gitops/bootstrap -n argocd | \
  kubeconform -strict -summary -kubernetes-version 1.35.0 \
    -schema-location default \
    -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'
```

## Things worth knowing

* **Namespaces come from Terraform**, because Terraform also puts the
  `mlflow-postgres` and `grafana-admin` secrets in them. Every Application
  therefore syncs with `CreateNamespace=false`.
* **No password is in this folder.** The two charts that need one read an
  existing secret.
* **Argo Rollouts syncs with `ServerSideApply=true`.** Its
  CustomResourceDefinitions are larger than the 256 KB that a normal apply
  stores in an annotation.
* **Deleting the root Application deletes everything.** Each child carries the
  finalizer `resources-finalizer.argocd.argoproj.io`. For a teardown, delete the
  root Application first and wait until the volumes are gone, and only then let
  Terraform remove Argo CD. Uninstalling Argo CD first leaves nothing to process
  those finalizers and the namespace hangs in `Terminating`.
* **Prune and self-heal are on.** Anything changed with `kubectl` is put back
  within a minute. The way to change something is a commit.
