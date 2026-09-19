# Homework 4 — MLflow experiments with Argo CD, PushGateway and Grafana

This assignment runs a series of training experiments, tracks them in MLflow and
shows the results in Grafana. Every service is deployed by Argo CD from Git.
Nothing is installed with `helm install` or `kubectl apply` by hand.

It builds on the two previous assignments: the EKS cluster from `lesson-5` and
Argo CD from `lesson-7`.

```
lesson-9/
├── argocd/
│   └── applications/          # one Argo CD Application per service
│       ├── minio.yaml
│       ├── postgres.yaml
│       ├── mlflow.yaml
│       ├── pushgateway.yaml
│       ├── prometheus.yaml    # added: no assignment installs it
│       └── grafana.yaml       # added: no assignment installs it
├── manifests/
│   └── postgres/              # plain manifests, see "Why PostgreSQL has no chart"
├── experiments/
│   ├── train_and_push.py
│   └── requirements.txt
├── best_model/                # written by the script
├── docs/                      # screenshots
└── README.md
```

## What is deployed, and where

| Service | Namespace | Chart | Version |
|---|---|---|---|
| MinIO | `mlflow` | `minio/minio` | 5.4.0 |
| PostgreSQL | `mlflow` | plain manifests | `postgres:17-alpine` |
| MLflow | `mlflow` | `community-charts/mlflow` | 1.11.7 (MLflow 3.16.0) |
| PushGateway | `monitoring` | `prometheus-community/prometheus-pushgateway` | 3.8.0 |
| Prometheus | `monitoring` | `prometheus-community/prometheus` | 29.27.2 |
| Grafana | `monitoring` | `grafana/grafana` | 10.5.15 |

How the data flows:

```
train_and_push.py ──► MLflow ──► PostgreSQL   (runs, parameters, metrics)
        │                └────► MinIO        (the model files)
        │
        └──────────► PushGateway ──► Prometheus ──► Grafana
```

## How Argo CD deploys all of it

The GitOps repository <https://github.com/MaksDeGreez/goit-argo> already has an
`ApplicationSet` from the previous assignment. It watches every folder under
`namespace/` and makes one Argo CD Application per folder.

For this assignment one more file was added there,
`namespace/infra-tools/mlops-platform.yaml`. It is a small root Application that
points at `lesson-9/argocd/applications/` in this repository. Argo CD reads that
folder and creates the six Applications it finds, and each of those installs its
own chart. This is called the "app of apps" pattern:

```
ApplicationSet
  └── Application "infra-tools"
        └── Application "mlops-platform"
              ├── Application "postgres"      (sync wave 0)
              ├── Application "minio"         (sync wave 0)
              ├── Application "pushgateway"   (sync wave 0)
              ├── Application "prometheus"    (sync wave 0)
              ├── Application "grafana"       (sync wave 0)
              └── Application "mlflow"        (sync wave 1)
```

The sync waves matter: MLflow is in wave 1, so Argo CD waits until PostgreSQL
and MinIO are healthy before it starts MLflow.

The advantage of this layout is that the Application manifests stay in the
homework project, where the assignment's folder structure puts them, while Argo
CD still picks them up from Git on its own.

## Three decisions worth explaining

### Why PostgreSQL has no Helm chart

The usual choice is the Bitnami PostgreSQL chart. Bitnami has removed its free
images from Docker Hub, so `bitnami/postgresql:17` can no longer be pulled — the
MLflow chart even says so in its own values file. The official `postgres` image
is small, has an arm64 build, and needs only a Deployment, a Service and a
Secret, so those three files are in `manifests/postgres/`. Argo CD deploys a
folder of plain manifests just as happily as a chart.

### Why nothing uses a PersistentVolume

The cluster has one StorageClass, `gp2`, and it still uses the old in-tree AWS
provisioner, which newer Kubernetes versions no longer include. There is no EBS
CSI driver installed, so any PersistentVolumeClaim would stay `Pending` for
ever. Every service therefore uses `emptyDir`.

That is acceptable here because the cluster is created for one session and
deleted afterwards. In a real setup the EBS CSI driver would be added as an EKS
add-on and MinIO and PostgreSQL would get real volumes.

### Why MLflow runs on the second node group

The EKS cluster has two node groups: `cpu-nodes` on arm64 and `gpu-nodes` on
x86_64, and the second one carries the taint `workload=gpu:NoSchedule`. MLflow is
the ML service of this project, so it is sent there on purpose with a
`nodeSelector` and a matching `toleration`. This puts the node group split from
the earlier assignment to real use and keeps the load off the other two nodes.

## Passwords

The database and MinIO passwords are written in the manifests. They are demo
values: the services are only reachable inside the cluster, and the whole
cluster is deleted at the end of the session. A real project would keep them out
of Git with Sealed Secrets, the External Secrets Operator or AWS Secrets
Manager. Grafana is different — its password is generated by the chart and read
from a Kubernetes secret, which is shown below.

## Running it

### 1. Check that everything is deployed

```bash
export AWS_PROFILE=goit
kubectl get applications -n infra-tools
```

All Applications should be `Synced` and `Healthy`. Then look at the pods:

```bash
kubectl get pods -n mlflow
kubectl get pods -n monitoring
```

To confirm the services and their ports:

```bash
kubectl get svc -n mlflow
kubectl get svc -n monitoring
```

MLflow must be `ClusterIP` on port 5000 and PushGateway `ClusterIP` on port
9091, which makes it reachable inside the cluster at
`http://pushgateway.monitoring.svc.cluster.local:9091`.

### 2. Open the port-forwards

The training script runs on your machine, so it needs two tunnels into the
cluster. Open each in its own terminal and leave it running:

```bash
kubectl -n mlflow port-forward svc/mlflow 5000:5000
```

```bash
kubectl -n monitoring port-forward svc/pushgateway 9091:9091
```

MinIO needs no port-forward. MLflow is started with `--serve-artifacts`, so the
client uploads the models through MLflow and only MLflow talks to MinIO.

There is one catch on the way back. When MLflow stores artifacts in an S3-like
store, it offers the client a direct download link to that store instead of
sending the file itself. The link points at
`minio.mlflow.svc.cluster.local:9000`, which only resolves inside the cluster,
so on a laptop the download fails and leaves a file of the right size with
nothing in it. The script therefore sets

```
MLFLOW_ENABLE_PROXY_MULTIPART_DOWNLOAD=false
```

before it imports `mlflow`, which makes the download go through the MLflow
server. It also checks afterwards that the downloaded files are not empty.

### 3. Run the training

```bash
cd experiments
uv venv --python 3.13
source .venv/bin/activate
uv pip install -r requirements.txt
python train_and_push.py
```

The script trains eight models, one for every combination of `C` and
`max_iter`. For each one it logs the parameters, the metrics and the model to
MLflow, and pushes `accuracy` and `loss` to PushGateway with the MLflow run id
as a label. At the end it picks the run with the best accuracy and copies that
model into `best_model/`.

### 4. Look at the runs in MLflow

Open <http://localhost:5000>, choose the experiment
`iris-logistic-regression` and you get one row per run with its parameters and
metrics. Open any run and the `Artifacts` tab shows the saved model.

### 5. Look at the metrics in Grafana

```bash
kubectl -n monitoring port-forward svc/grafana 3000:80
```

The user name is `admin`. The password is generated by the chart:

```bash
kubectl -n monitoring get secret grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

Open <http://localhost:3000>, go to **Explore**, pick the **Prometheus** data
source (it is already configured, no setup needed) and query:

```
mlflow_accuracy
mlflow_loss
```

There is one series per training run. Switch the view to **Table** to see all
runs at once with their `run_id`, `c` and `max_iter` labels.

If nothing appears, check that Prometheus has scraped PushGateway:

```bash
kubectl -n monitoring port-forward svc/prometheus-server 9090:80
```

then open <http://localhost:9090/targets> and look for the `pushgateway` job.

## What the run produced

The eight runs, as they appear in MLflow:

| C | max_iter | accuracy | loss |
|---|---|---|---|
| 0.01 | 100 | 0.8000 | 0.6455 |
| 0.01 | 500 | 0.8000 | 0.6455 |
| 0.1 | 100 | 0.9667 | 0.3499 |
| 0.1 | 500 | 0.9667 | 0.3499 |
| 1.0 | 100 | 0.9667 | 0.1589 |
| 1.0 | 500 | 0.9667 | 0.1589 |
| **10.0** | **100** | **1.0000** | **0.0754** |
| 10.0 | 500 | 1.0000 | 0.0759 |

Two things are worth noticing. A stronger `C` means weaker regularisation, and on
this small dataset that keeps helping all the way to the end. And `max_iter`
changes almost nothing, because the solver already stops early for the low
values of `C`; only at `C=10.0` does it still want more steps, which is why
scikit-learn prints a convergence warning there.

The best run wins on accuracy, and the tie with the other `C=10.0` run is broken
by the lower loss:

```
Best run:
  run_id   0a4d47df83c44d36abcf7e05f97a6b34
  C        10.0
  max_iter 100
  accuracy 1.0000
  loss     0.0754

Best model copied to .../lesson-9/best_model
  MLmodel  (681 bytes)
  conda.yaml  (198 bytes)
  model.skops  (8981 bytes)
  python_env.yaml  (98 bytes)
  registered_model_meta  (37 bytes)
  requirements.txt  (89 bytes)
```

Both metrics arrive in Prometheus as eight separate series, one per run:

```
mlflow_accuracy{c="10.0", max_iter="100", run_id="0a4d47df83c4...", job="mlflow_training"}  1
mlflow_loss{c="10.0", max_iter="100", run_id="0a4d47df83c4...", job="mlflow_training"}      0.0754
```

The `run_id`, `c` and `max_iter` labels survive the trip only because Prometheus
scrapes PushGateway with `honor_labels: true`. Without it Prometheus would
replace them with its own job and instance labels and every run would look the
same.

## Screenshots

| File | What it shows |
|---|---|
| `docs/01-argocd-applications.png` | all Applications in the Argo CD UI |
| `docs/02-kubectl-applications.png` | `kubectl get applications` |
| `docs/03-pods.png` | the pods in the `mlflow` and `monitoring` namespaces |
| `docs/04-train-output.png` | the output of `train_and_push.py` |
| `docs/05-mlflow-runs.png` | the run list in the MLflow UI |
| `docs/06-mlflow-artifacts.png` | the saved model in the MLflow UI |
| `docs/07-best-model.png` | the contents of `best_model/` |
| `docs/08-grafana-accuracy.png` | `mlflow_accuracy` in Grafana Explore |
| `docs/09-grafana-loss.png` | `mlflow_loss` in Grafana Explore |

## Deleting everything

This assignment adds no infrastructure of its own, so there is nothing to
destroy here. Deleting the file `namespace/infra-tools/mlops-platform.yaml` from
the GitOps repository and pushing removes every service again, because Argo CD
prunes what is no longer in Git.

To remove the whole cluster, use the order from the earlier assignments:

```bash
cd ../lesson-7/terraform/argocd && terraform destroy
kubectl delete namespace application mlflow monitoring
cd ../../../lesson-5/eks && terraform destroy
cd ../vpc && terraform destroy
```

The S3 bucket that holds the Terraform state is kept on purpose.
