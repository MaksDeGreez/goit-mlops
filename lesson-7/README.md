# Homework 3 — Argo CD on EKS with Terraform

This assignment installs Argo CD into the EKS cluster from the previous
assignment and connects it to a separate Git repository that holds the
Kubernetes manifests. After that, a `git push` is enough to change the cluster.

GitOps repository: <https://github.com/MaksDeGreez/goit-argo>

```
lesson-7/
└── terraform/
    └── argocd/
        ├── main.tf                        # two helm_release resources
        ├── provider.tf                    # aws, kubernetes and helm providers
        ├── variables.tf
        ├── outputs.tf
        ├── terraform.tf
        ├── backend.tf                     # S3 state, key argocd/terraform.tfstate
        └── values/
            ├── argocd-values.yaml         # settings of the argo-cd chart
            └── argocd-apps-values.yaml    # the ApplicationSet
```

## How it works

1. Terraform installs the `argo-cd` Helm chart into the namespace `infra-tools`.
2. Terraform installs a second small chart, `argocd-apps`, which only creates
   one `ApplicationSet` object.
3. The ApplicationSet uses a *git directory generator*. It looks at the folders
   that match `namespace/*` in the GitOps repository and creates one Argo CD
   Application per folder.
4. Each Application deploys the files of its folder into the namespace with the
   same name, and keeps them in sync automatically.

Two Helm releases are used instead of one because an `ApplicationSet` is a
custom resource. Its definition only exists after Argo CD is installed, so the
object cannot be created in the same step. `depends_on` puts them in order.

Today the repository has two folders, so Argo CD creates two Applications:

| Folder | Application | What it deploys |
|---|---|---|
| `namespace/infra-tools/` | `infra-tools` | the namespace Argo CD runs in |
| `namespace/application/` | `application` | namespace, demo Nginx Deployment and Service |

Adding a third folder is enough to get a third Application. Nothing in the
Terraform code has to change.

## What is in `argocd-values.yaml`

| Setting | Value | Why |
|---|---|---|
| `server.service.type` | `ClusterIP` | No load balancer, so nothing costs money and the UI is not open to the internet. It is reached with `kubectl port-forward`. |
| `server.extraArgs` | `--insecure` | The server speaks plain HTTP. TLS is not needed behind a port-forward, and it avoids a browser warning about a self-signed certificate. |
| `configs.rbac` | default role `readonly`, group `admin` mapped to a `platform-admin` role | Anyone who logs in can only look at the applications unless they are mapped to an admin role. |
| `configs.cm.timeout.reconciliation` | `60s` | How often Argo CD looks at Git. The default is 3 minutes; 60 seconds makes a change appear faster. |
| `configs.cm.timeout.hard.reconciliation` | `0s` | Turns off the extra full refresh on a timer. |
| `global.nodeSelector` | `workload: cpu` | Sends every Argo CD pod to the `cpu-nodes` group from the previous assignment. |
| `dex.enabled` | `false` | Dex is only needed for logins through GitHub or Google. This project uses the local admin user, so one pod less runs. |

## Before you start

The EKS cluster of assignment 2 must be running, and `kubectl` must already
work:

```bash
export AWS_PROFILE=goit
aws eks --region us-east-1 update-kubeconfig --name goit-mlops-eks
kubectl get nodes
```

Terraform reads the cluster address and certificate with a data source and asks
the AWS CLI for a short-lived token on every run, so no cluster credentials are
stored anywhere.

## How to run

```bash
cd terraform/argocd
terraform init
terraform apply
```

Takes about 3 minutes. It ends with the outputs, including the command for the
UI and the first admin password.

## How to check it

### Argo CD is running

```bash
kubectl get pods -n infra-tools
```

Expected: several pods with the prefix `argocd-`, all `Running`.

### Open the UI

```bash
kubectl -n infra-tools port-forward svc/argocd-server 8080:80
```

Open <http://localhost:8080>. The user name is `admin`. The password is either

```bash
terraform output -raw argocd_admin_password
```

or, straight from the cluster:

```bash
kubectl -n infra-tools get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d
```

### The ApplicationSet created the Applications

```bash
kubectl get applicationset -n infra-tools
kubectl get applications -n infra-tools
```

Expected: one ApplicationSet named `namespaces`, and two Applications,
`application` and `infra-tools`, both `Synced` and `Healthy`.

### The demo application is deployed

```bash
kubectl get deploy -n application
kubectl get pods -n application
```

Expected: the deployment `demo-nginx` with 2 ready pods.

### The demo application answers

```bash
kubectl -n application port-forward deployment/demo-nginx 8081:80
curl -I http://localhost:8081
```

Expected: `HTTP/1.1 200 OK` and the Nginx welcome page in a browser.

### The GitOps loop really works

Change something in the GitOps repository, for example the number of replicas
in `namespace/application/demo-nginx.yaml`, then commit and push. Within about
a minute:

```bash
kubectl get pods -n application -w
```

The number of pods follows the file. Nothing was applied by hand.

## What the run produced

```
$ kubectl get pods -n infra-tools
NAME                                                READY   STATUS    RESTARTS   AGE
argocd-application-controller-0                     1/1     Running   0          2m2s
argocd-applicationset-controller-668bb8d7f5-x9hzq   1/1     Running   0          17m
argocd-notifications-controller-5578f5fc69-fw5jj    1/1     Running   0          17m
argocd-redis-78985698c5-2kht5                       1/1     Running   0          2m4s
argocd-repo-server-5f765fbcdb-ss2th                 1/1     Running   0          2m3s
argocd-server-5b8674f894-98kpf                      1/1     Running   0          17m

$ kubectl get applicationset -n infra-tools
NAME         AGE
namespaces   16m

$ kubectl get applications -n infra-tools
NAME          SYNC STATUS   HEALTH STATUS
application   Synced        Healthy
infra-tools   Synced        Healthy
```

There is no `dex` pod, because Dex is turned off in the values file.

The GitOps loop was then tested for real. The file
`namespace/application/demo-nginx.yaml` in the GitOps repository was changed
from two replicas to three, committed and pushed. Nothing else was done:

```
$ kubectl get deploy,pods -n application
NAME                         READY   UP-TO-DATE   AVAILABLE   AGE
deployment.apps/demo-nginx   3/3     3            3           16m

NAME                              READY   STATUS    RESTARTS   AGE
pod/demo-nginx-67fcd68777-zskdt   1/1     Running   0          16m
pod/demo-nginx-67fcd68777-m5q42   1/1     Running   0          6m32s
pod/demo-nginx-67fcd68777-szqhg   1/1     Running   0          2m6s
```

The ages of the pods tell the story: the first pods are as old as the
deployment, the last one appeared shortly after the push. Argo CD noticed the
new commit and created it.

Screenshots of all these steps are in [`docs/`](docs/):

| File | What it shows |
|---|---|
| `01-argocd-apply.png` | `terraform apply` and its outputs |
| `02-argocd-pods.png` | the Argo CD pods in `infra-tools` |
| `03-applications-synced.png` | the ApplicationSet and both Applications |
| `04-argocd-ui.png` | the Argo CD UI with both applications green |
| `05-demo-nginx-deployed.png` | the demo Deployment with its first two pods |
| `06-demo-nginx-page.png` | the Nginx page through `kubectl port-forward` |
| `07-gitops-push-scales-app.png` | `kubectl get pods -w` while a third pod appears after the `git push` |

## How to delete everything

```bash
cd terraform/argocd
terraform destroy
```

Deleting the ApplicationSet also deletes the Applications it created, but the
objects those Applications deployed are left behind, because the Applications
carry no deletion finalizer. Remove them with one command:

```bash
kubectl delete namespace application
```

After that, destroy the cluster and the network of the previous assignment, in
that order:

```bash
cd ../../../lesson-5/eks && terraform destroy
cd ../vpc && terraform destroy
```

## Cost

Argo CD itself adds nothing to the bill. It runs on the nodes that already
exist, and the service type is `ClusterIP`, so there is no load balancer.
The cost of this assignment is the cost of the cluster from assignment 2,
about $0.25 per hour.
