# Final project — an MLOps platform on AWS

An end-to-end MLOps platform on AWS EKS. Terraform builds the AWS side, Argo CD
deploys everything that runs in the cluster, a self-hosted MLflow server keeps
the experiments and the model versions, and a FastAPI service serves one
version of the model. New versions go out as canary releases with Argo
Rollouts, and a bad one rolls itself back. Prometheus, Grafana and Loki collect
metrics and logs, Evidently checks the live data for drift, and GitHub Actions
runs the pipelines.

The model is a small scikit-learn regression on the California Housing dataset.
That is on purpose: the project is about the platform, not about the model.

## Contents

- [Demo trace](#demo-trace)
- [Architecture](#architecture)
- [Repository structure](#repository-structure)
- [Requirements](#requirements)
- [Deploy from zero](#deploy-from-zero)
- [Namespaces](#namespaces)
- [Access to the user interfaces](#access-to-the-user-interfaces)
- [Observability](#observability)
- [Model registry and promotion](#model-registry-and-promotion)
- [Deployment strategy](#deployment-strategy)
- [Rollback](#rollback)
- [Security baseline](#security-baseline)
- [Tests and CI](#tests-and-ci)
- [Run everything locally](#run-everything-locally)
- [Code quality](#code-quality)
- [Cost](#cost)
- [Teardown](#teardown)
- [Documents](#documents)

## Demo trace

The system really ran on AWS on 21 September 2026: cluster `mlops-final` in
`us-east-1`, Kubernetes 1.35.8, two `t4g.large` arm64 nodes. This section shows
the four states the assignment asks for. The whole story, in the order it
happened, is in [`docs/demo-trace.md`](docs/demo-trace.md).

**1. Every Argo CD Application Synced and Healthy.** One root Application and
fourteen children, in four sync waves:

![all fifteen Applications healthy in the Argo CD UI](docs/screenshots/20-argocd-ui-all-healthy.png)

![the same list from the command line](docs/screenshots/18-argocd-applications-cli.png)

**2. The MLflow Model Registry with a model in Production.** With the *New
model registry UI* switch turned off, MLflow shows the stages the assignment
words the workflow in — here right after version 2 was promoted and version 1
archived:

![version 2 Production, version 1 Archived](docs/screenshots/32-mlflow-v2-production-v1-archived.png)

The same registry with the aliases and the tags that make a version traceable:
the Git commit, the dataset hash, the model checksum, the three metrics, the
MLflow run id, and `promoted_at` / `promoted_by` written by the promotion hook:

![version 1 under the alias production, with all its tags](docs/screenshots/29-mlflow-v1-production.png)

**3. A Grafana dashboard with live monitoring.** Request rate, error share, p95
latency, pods with a model loaded, everything split by model version, pod CPU
and memory, and the newest log lines from Loki:

![the inference dashboard](docs/screenshots/23-grafana-inference-dashboard.png)

**4. A successful CI pipeline run.** All ten jobs of `final-project-ci`,
including the image push to ECR through OIDC, and the training pipeline started
from the Actions tab:

![push-images green with the pushed tag](docs/screenshots/15-ci-push-images-green.png)

![a training run started from the Actions tab](docs/screenshots/16-ci-training-run-green.png)

### The rest of the story

| Step | What it shows | Screenshots |
|---|---|---|
| [The cluster is up](docs/demo-trace.md#1-the-cluster-is-up) | 75 + 31 Terraform resources, 110 pods per node, 47 pods running | 17, 19 |
| [Argo CD deploys everything](docs/demo-trace.md#2-argo-cd-deploys-everything) | fifteen Applications, four waves, the two fixes the first deploy needed | 18, 20 |
| [Training through Step Functions](docs/demo-trace.md#3-a-training-run-through-step-functions) | GitHub → OIDC → Step Functions → Kubernetes Job → MLflow, 54 s | 22, 21 |
| [The first promotion](docs/demo-trace.md#4-the-first-promotion) | canary 10 → 50 → 100 %, nine good measurements, the audit line | 25, 26, 27, 28, 29 |
| [Version 2, with traffic](docs/demo-trace.md#5-version-2-with-traffic) | both versions serving, archive + promote in one hook run | 30, 31, 33, 32 |
| [Rollback with git revert](docs/demo-trace.md#6-rollback-with-git-revert) | one command, the registry follows | 34, 35 |
| [The canary that aborted by itself](docs/demo-trace.md#7-the-canary-that-aborted-by-itself) | bonus G2: 0.548 against a limit of 0.05, aborted in two minutes | 36, 37, 38, 39 |
| [Live monitoring](docs/demo-trace.md#8-live-monitoring) | the inference dashboard | 23 |
| [Drift and the alert](docs/demo-trace.md#9-drift-and-the-alert-that-fired) | PSI per feature, share 0.375, the rule Firing | 40, 41, 42 |
| [Security proofs](docs/demo-trace.md#10-security-rbac-bad-input-rate-limit-audit-trail) | 32 of 32 RBAC answers, 400, 429, the audit trail | 43, 44, 45 |
| [What it costs](docs/demo-trace.md#11-what-it-costs) | bonus G4: $0.135 per hour inside the cluster | 46 |

There is no public link to the running system: nothing in this project is
exposed to the internet, on purpose. See
[Access to the user interfaces](#access-to-the-user-interfaces) for the
`kubectl port-forward` commands that open each one.

## Architecture

```mermaid
flowchart TB
    dev["Developer<br/>git push"] --> gh["GitHub Actions<br/>lint, tests, Trivy, gitleaks"]
    gh -- "OIDC, no stored keys" --> ecr
    gh -- "start-execution" --> sfn
    gitops["This repository<br/>final-project/gitops"] --> argo
    tf["Terraform<br/>stacks/infra, then stacks/platform"] --> ecr & sfn & s3 & argo

    subgraph aws["AWS account"]
        ecr["ECR<br/>4 repositories, immutable tags"]
        sfn["Step Functions + 2 Lambdas<br/>ValidateInput, RunTrainingJob, LogMetrics"]
        s3["S3<br/>model artifacts, versioned"]
    end

    subgraph eks["EKS cluster mlops-final, 2 x t4g.large arm64"]
        argo["Argo CD + Argo Rollouts<br/>ns argocd"]

        subgraph sys["ns mlops-system"]
            job["Training Job"]
            mlf["MLflow<br/>tracking and registry"]
            pg[("PostgreSQL")]
            drift["drift-monitor CronJob<br/>Evidently, every 15 min"]
        end

        subgraph serve["ns staging and ns production"]
            istg["inference, staging<br/>follows the alias"]
            iprod["inference, production<br/>canary Rollout, 10 pods<br/>version + sha256 from Git"]
            hook["registry-sync Job<br/>PostSync hook"]
        end

        subgraph mon["ns monitoring"]
            prom["Prometheus"]
            loki["Loki + Alloy"]
            graf["Grafana<br/>dashboards and alerts"]
            pgw["PushGateway"]
            oc["OpenCost"]
        end
    end

    %% One Application per component, in four sync waves.
    argo -- "app of apps, 14 Applications" --> sys
    argo --> serve & mon
    sfn -- "eks:runJob.sync" --> job
    job -- "new version, alias staging" --> mlf
    mlf --- pg
    mlf -- "artifacts" --> s3
    istg -- "by alias" --> mlf
    iprod -- "by version + sha256" --> mlf
    hook -- "move alias and stage" --> mlf
    istg & iprod -- "metrics" --> prom
    istg & iprod -- "JSON logs" --> loki
    drift -- "drift metrics" --> pgw
    pgw & oc --> prom
    prom & loki --> graf
    loki -- "prediction lines" --> drift
    prom -- "5xx of the new version" --> iprod
```

Two things are worth reading twice:

- **Terraform stops at Argo CD.** It creates AWS resources, the namespaces and
  the two generated passwords, then installs Argo CD and one root Application.
  Everything else is deployed from `gitops/` by Argo CD. There is no
  `kubectl apply` and no `helm install` in any instruction below.
- **Training and deployment are separate pipelines.** Training is started by
  hand from a workflow and ends with a new version under the alias `staging`.
  Deployment to production is a commit that changes two lines in a values file.

## Repository structure

```
final-project/
├── terraform/                  AWS, in two stacks
│   ├── modules/
│   │   ├── vpc/                network, two AZs, one NAT gateway
│   │   ├── eks/                cluster, arm64 node group, add-ons, access entries
│   │   ├── ecr/                four image repositories, immutable tags
│   │   ├── ci-access/          GitHub OIDC provider and the CI role
│   │   ├── argocd/             the argo-cd chart and the root Application
│   │   ├── mlflow/             S3 bucket, Pod Identity role, the Postgres secret
│   │   ├── monitoring/         the Grafana admin secret
│   │   └── training-pipeline/  two Lambdas and the Step Functions state machine
│   └── stacks/
│       ├── infra/              vpc + eks + ecr + ci-access      (apply first)
│       └── platform/           namespaces + mlflow + monitoring + pipeline + argocd
├── gitops/                     everything Argo CD deploys
│   ├── bootstrap/              the app-of-apps chart: one Application per component
│   ├── apps/<name>/            values of a third-party chart, or plain manifests
│   ├── charts/inference/       our chart: Rollout, Service, analysis, registry hook
│   ├── charts/drift-monitor/   our chart: the CronJob
│   └── envs/                   staging.yaml and production.yaml — edited day to day
├── rbac/                       roles for mlops-engineer, viewer and the pipeline
├── lambda/                     the two Lambda handlers of the training pipeline
├── services/
│   ├── training/               trains a model and registers a version
│   ├── inference/              FastAPI service that serves one version
│   ├── registry-ops/           promote, roll back, delete, with an audit line
│   └── drift-monitor/          Evidently job that looks for data drift
├── scripts/                    state bucket, dataset, traffic, local e2e, validation
├── data/                       the California Housing snapshot and the reference sample
├── docs/                       screenshots, threat model, escalation policy
├── docker-compose.yml          the whole stack on one machine
├── .gitlab-ci.yml              the same pipeline written for GitLab
├── README.md   RUNBOOK.md   ADR.md
```

The two GitHub workflows are at **`.github/workflows/`** in the root of the
repository, because GitHub only reads workflows from there:

| Workflow | Trigger | What it does |
|---|---|---|
| `final-project-ci.yml` | push and pull request on `final-project` | lint, tests, Terraform, GitOps, image build and scan, secret scan, image push |
| `final-project-train.yml` | manual | starts the training pipeline and waits for the result |

## Requirements

| Tool | Version | Used for |
|---|---|---|
| Terraform | 1.10 or newer | creating the infrastructure (`use_lockfile` needs 1.10) |
| AWS CLI | 2.x | access to the account, `aws eks update-kubeconfig` |
| kubectl | 1.30 or newer | working with the cluster |
| Helm | 3 or 4 | checking charts before Argo CD syncs them |
| Docker | any recent | building the service images and the local stack |
| uv | 0.8 or newer | Python 3.13 and the Python tools |
| `kubectl-argo-rollouts` | 1.10 | watching a canary and aborting one by hand. The runbook uses it; plain `kubectl` can show the state of a Rollout but cannot abort it. |
| kubeconform, kustomize, yq | 0.8 / 5.8 / 4.53 | only for `scripts/validate_gitops.sh` |

An AWS account with administrator rights, and a profile named `goit`
(`aws_profile` is a variable if the name is different; the two `backend` blocks
hardcode it, because a backend block cannot use variables).

Install the plugin for the canary commands:

```bash
brew install argoproj/tap/kubectl-argo-rollouts
```

## Deploy from zero

Ten steps, numbered 0 to 9. Nothing happens outside this list. Paths without a
leading `/` are relative to `final-project/`, and every block says where to
`cd` when it is somewhere else.

### Step 0 — prerequisites and the state bucket

Terraform keeps its state in S3, so the state does not depend on which branch
is checked out. The bucket is **not** managed by Terraform: if it were,
`terraform destroy` would delete the state file it is supposed to protect.

It already exists for this account. On an empty account, create it once:

```bash
cd final-project
BUCKET=my-tfstate-bucket-<something unique> AWS_PROFILE=goit \
  ./scripts/create_state_bucket.sh
```

The script is safe to run again. It creates the bucket, blocks all public
access, turns on versioning and turns on AES256 encryption. If you used your
own name, change the `bucket` line in `terraform/stacks/infra/backend.tf` and
`terraform/stacks/platform/backend.tf`.

Locking is `use_lockfile = true`, so there is no DynamoDB table.

### Step 1 — the infra stack

```bash
cd final-project/terraform/stacks/infra
terraform init
terraform apply
```

**75 resources, about 18 minutes** when it was really applied; almost all of
that is the EKS control plane. This creates the VPC, the cluster with one arm64
node group, the four ECR repositories, the GitHub OIDC provider and the CI
role.

Write down two outputs:

```bash
terraform output ci_role_arn                 # -> repository variable FINAL_AWS_ROLE_ARN
terraform output update_kubeconfig_command
```

### Step 2 — point kubectl at the cluster

```bash
aws eks update-kubeconfig --name mlops-final --region us-east-1 --profile goit
kubectl get nodes          # two nodes, Ready
```

Two things are worth checking here, because both are silent when they go wrong:

```bash
# 110 and not 35: the VPC CNI is using prefix delegation
kubectl get nodes -o custom-columns=NAME:.metadata.name,MAXPODS:.status.allocatable.pods

# ebs-csi-default-sc must be marked (default), or every PVC waits for ever
kubectl get storageclass
```

### Step 3 — repository variables, and push the images

In GitHub: **Settings → Secrets and variables → Actions → Variables**. These
are *variables*, not secrets: none of them is confidential on its own, and a
variable is visible in the log, which makes a failing run much easier to read.

| Variable | Value | From |
|---|---|---|
| `FINAL_AWS_ROLE_ARN` | `arn:aws:iam::<account-id>:role/mlops-final-github-actions` | step 1, output `ci_role_arn` |
| `AWS_REGION` | `us-east-1` | |
| `FINAL_STATE_MACHINE_ARN` | filled in at step 5 | |

The names start with `FINAL_` on purpose: this repository also holds the homework of lesson 10,
which uses the plain names `AWS_ROLE_ARN` and `STATE_MACHINE_ARN` for a role that no longer exists.
Sharing them would make this pipeline try to assume that old role.

With `FINAL_AWS_ROLE_ARN` set, the `push-images` job stops being skipped. Run it
once: **Actions → final-project-ci → Run workflow** on branch `final-project`.
It builds the four images and pushes them to ECR tagged with the **full 40
character commit SHA**, and prints the result in the job summary without the
registry host (the host contains the account id and this repository is public).

GitHub only shows the **Run workflow** button for workflows that exist on the
default branch. If the button is missing (the workflow only lives on another
branch), open the last run of `final-project-ci` and press **Re-run all jobs**,
or push any commit under `final-project/`: both start the same pipeline, now
with the variable set.

Copy that commit SHA. Step 4 needs it.

### Step 4 — point the charts at the images you just pushed

This is the one order that has to be right. Argo CD syncs the inference and
drift Applications in the last wave; if the tag in Git names an image that is
not in ECR, those pods sit in `ImagePullBackOff`. So the images go first and
the tags are set **before** Argo CD ever runs.

Edit four lines to the SHA from step 3:

| File | Key |
|---|---|
| `gitops/envs/staging.yaml` | `imageTag` |
| `gitops/envs/production.yaml` | `imageTag` |
| `gitops/envs/production.yaml` | `registryOpsImageTag` |
| `gitops/charts/drift-monitor/values.yaml` | `imageTag` |

```bash
git commit -am "Deploy the images of <sha>"
git push
```

This push starts CI again and pushes a second set of images under the new
commit SHA. That is harmless: the tags in the files still name the images from
step 3, which exist.

> **Change `registryOpsImageTag` together with something else.** That key is
> only read by the `PostSync` hook Job, and a hook Job is not part of the
> desired state Argo CD compares against the cluster. On its own it therefore
> leaves the Application `Synced`, no sync runs, and the hook keeps using the
> old image until the next real change. Here it is changed in the same commit
> as `imageTag`, so there is nothing to do. If it ever has to change alone,
> press **Sync** on `inference-production` in the Argo CD UI.

### Step 5 — the platform stack

```bash
cd final-project/terraform/stacks/platform
terraform init
terraform apply
```

**31 resources, about six minutes.** This creates the five namespaces, the two
generated secrets, the MLflow S3 bucket and its Pod Identity role, the two
Lambdas and the Step Functions state machine, and finally Argo CD with one root
Application.

Now fill in the third repository variable:

```bash
terraform output state_machine_arn     # -> repository variable FINAL_STATE_MACHINE_ARN
```

### Step 6 — watch Argo CD sync

```bash
kubectl -n argocd port-forward svc/argocd-server 8080:80
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo
```

Open <http://localhost:8080> and log in as `admin`. The root Application
`mlops-platform` creates fourteen child Applications and syncs them in waves:

| Wave | Applications |
|---|---|
| 0 | `rbac`, `argo-rollouts`, `postgres` |
| 1 | `mlflow`, `prometheus`, `pushgateway`, `loki` |
| 2 | `alloy`, `grafana`, `grafana-dashboards`, `opencost` |
| 3 | `inference-staging`, `inference-production`, `drift-monitor` |

From the command line:

```bash
kubectl -n argocd get applications
kubectl get pods -A
```

All fifteen Applications were `Synced` and `Healthy` about **eight minutes**
after the platform stack finished.

**Expected at this point:** the inference pods start but stay **not ready**.
There is no model in the registry yet, so `/health/ready` answers 503 and both
inference Applications show `Progressing`. That is the design: a pod without a
checked model never takes traffic. It is fixed by the next step.

**Also expected, and harmless:** two restart counters after the very first
sync. The twelve inference pods show `RESTARTS 1` because they started before
MLflow was reachable and failed the startup probe once; `opencost` shows
`RESTARTS 2` because it waits for Prometheus, which is in a later wave. Both
settle by themselves and neither needs an action.

### Step 7 — the first training run

**Actions → final-project-train → Run workflow.** Leave every input empty.

![a training run started from the Actions tab](docs/screenshots/16-ci-training-run-green.png)

A second run with `max_iter` set to 50 gives a smaller model, so version 2 really differs from
version 1 (different checksum, slightly worse metrics):

![the second training run](docs/screenshots/24-ci-training-run-v2.png)

The same rule applies here: the button needs the workflow file on the default
branch. Pick `final-project` in the branch list of the dialog, so the workflow
and the code of that branch are used. Without the button, the same run can be
started from a terminal with the command that `terraform output
start_training_command` prints in `stacks/platform`.

The workflow starts the state machine, which validates the input, runs a
Kubernetes Job in `mlops-system` with the training image, waits for it, reads
the `training_finished` line out of the pod's logs and returns it. The job
summary then shows the version, `rmse`, `mae`, `r2`, `run_id`,
`dataset_sha256` and `model_sha256`.

Measured: the Step Functions execution took **54 seconds** and the whole
workflow **1 minute 18 seconds**. The two runs that were used for the demo:

| Run | Parameters | Version | rmse | mae | r2 |
|---|---|---|---|---|---|
| 1 | defaults (`max_iter` 200) | 1 | 0.4453 | 0.2947 | 0.8487 |
| 2 | `max_iter` 50 | 2 | 0.4897 | 0.3297 | 0.8170 |

Run 1 gives exactly the same numbers as a local run on the same data, which is
what pinning the dataset hash is for.

### Step 8 — staging picks it up, then promote

The training job gives the new version the alias `staging`. The staging pods
check that alias every 60 seconds and load the new model without restarting.

```bash
kubectl -n staging port-forward svc/inference 8000:80
curl -s localhost:8000/info | jq
curl -s localhost:8000/health/ready -o /dev/null -w '%{http_code}\n'   # 200
```

When it looks right, promote it. Edit two lines in
`gitops/envs/production.yaml` with the numbers from step 7:

```yaml
modelVersion: "1"
modelSha256: "<the 64 hex characters>"
```

```bash
git commit -am "Promote model version 1 to production"
git push
```

Argo CD syncs within a minute. The ten pods were already running and following
the alias, so pinning a version is a normal change of the pod template and Argo
Rollouts runs the full canary: one pod, a two minute pause, five pods, a two
minute pause, all ten. Measured end to end: **about five minutes**, with nine
successful background measurements.

When the Rollout is healthy, the `PostSync` hook Job runs
`registry_ops sync --production-version 1`, which sets the alias `production`
and the stage `Production` and prints one JSON audit line. That Job took 9
seconds.

### Step 9 — verify

Back in `final-project/`:

```bash
# every Application Synced and Healthy
kubectl -n argocd get applications

# production serves the pinned version
kubectl -n production port-forward svc/inference 8000:80 &
curl -s localhost:8000/info | jq '.model_version, .model_sha256'

# the registry agrees
kubectl -n production logs job/inference-registry-sync

# traffic, so the dashboards and the drift job have something to show
scripts/cluster_traffic.sh production --mode normal --count 3000 --rate 10
```

Send the traffic **from inside the cluster**, not through a port-forward. A
port-forward connects to one single pod, so during a canary it would hit either
only the new version or only the old one. `scripts/cluster_traffic.sh` runs a
small throw-away pod that calls the Service instead, and
`scripts/cluster_traffic.sh clean` removes it afterwards.

Then open Grafana (below) and look at the *Inference* dashboard. After the next
quarter of an hour the drift CronJob has run and the *Model quality* dashboard
has numbers as well.

What all of this looked like on the real cluster, step by step and with the
measured numbers, is in [`docs/demo-trace.md`](docs/demo-trace.md).

## Namespaces

One cluster, five namespaces. All of them are created by Terraform, never by
Argo CD, because Terraform also writes the two generated secrets into them.
Every Application therefore syncs with `CreateNamespace=false`.

| Namespace | What lives there | Who may change it |
|---|---|---|
| `argocd` | Argo CD server, controller, repo server, Redis; the root Application and its fourteen children | nobody by hand — it is Terraform and Git |
| `mlops-system` | MLflow, PostgreSQL, the Argo Rollouts controller, the training Jobs started by Step Functions, the drift CronJob | `mlops-engineers`: read and port-forward |
| `staging` | one inference release that follows the alias `staging` | `mlops-engineers`: full access, including Secrets and `exec` |
| `production` | one inference release pinned to a version and a checksum, plus the registry-sync hook Job | `mlops-engineers`: read, port-forward, and abort a canary — no writes |
| `monitoring` | Prometheus, Grafana, Loki, Alloy, PushGateway, OpenCost, the Grafana admin secret | `mlops-engineers`: read and port-forward |

The boundary between staging and production is the point of the split:
**staging follows an alias and changes by itself; production only changes
through a commit.** The RBAC in [`rbac/`](rbac/README.md) enforces it — an
engineer who could `patch` the production Rollout could change what runs
without a commit, so that right is not granted.

## Access to the user interfaces

**Nothing in this project is public**, and that is a decision, not a gap:

- There is no attack surface on the internet. MLflow and the Prometheus UI have
  no login at all, so publishing them would mean putting authentication in
  front of them first.
- No load balancer, no Route 53 zone, no ACM certificate: the cluster costs
  $0.28 an hour and an ALB would add about a third to that for no benefit.
- `ingress-nginx` was archived in March 2026 and receives no fixes, so the
  obvious free option is not one any more.

The cost is that a reviewer needs `kubectl` and this section instead of a link.
Each command opens one port and holds it until `Ctrl+C`.

| What | Command | Address | Login |
|---|---|---|---|
| Argo CD | `kubectl -n argocd port-forward svc/argocd-server 8080:80` | <http://localhost:8080> | `admin`, password below |
| MLflow | `kubectl -n mlops-system port-forward svc/mlflow 5001:5000` | <http://localhost:5001> | none |
| Grafana | `kubectl -n monitoring port-forward svc/grafana 3000:80` | <http://localhost:3000> | `admin`, password below |
| Prometheus | `kubectl -n monitoring port-forward svc/prometheus-server 9090:80` | <http://localhost:9090> | none |
| inference, production | `kubectl -n production port-forward svc/inference 8000:80` | <http://localhost:8000> | none |
| inference, staging | `kubectl -n staging port-forward svc/inference 8001:80` | <http://localhost:8001> | none |

```bash
# Argo CD: created by the chart on the first install
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo

# Grafana: generated by Terraform (random_password) and written into a Secret
kubectl -n monitoring get secret grafana-admin \
  -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

No password is ever printed by `terraform output`. The outputs give the
`kubectl` command that reads the secret when it is needed, so the value never
lands in a terminal scrollback or in a screenshot by accident.

MLflow is forwarded to 5001 because macOS uses 5000 for AirPlay; `5000:5000`
works everywhere else. MLflow 3 checks the `Host` header including the port, so
any port used here has to be covered by `serverAllowedHosts` in
`gitops/apps/mlflow/values.yaml` — it allows `localhost:*` and `127.0.0.1:*`.

> A port-forward binds to one **pod**, not to the Service. Restarting that pod
> kills the forward without a message. It is also the reason traffic for a
> canary has to come from inside the cluster
> (`scripts/cluster_traffic.sh`): a forward would send every request to the
> same pod.

## Observability

### Metrics

The inference service exports the defaults of
`prometheus-fastapi-instrumentator` plus six custom metrics. Every one of them
carries the model version, which is what makes a canary comparable with the
version it is replacing.

| Metric | Labels | What it answers |
|---|---|---|
| `inference_requests_total` | `model_version`, `status_class` | request rate and error rate, per version |
| `inference_request_duration_seconds` | `model_version` | latency, histogram from 2 ms to 2.5 s |
| `inference_predictions_total` | `model_version` | how much traffic a version really served |
| `inference_prediction_value` | `model_version` | the answers themselves, to see a version go wrong |
| `inference_model_info` | `model_name`, `model_version`, `model_sha256` | which model a pod has loaded |
| `inference_model_load_failures_total` | `reason` | failed loads, `checksum_mismatch` above all |

Pod CPU and memory come from cAdvisor and kube-state-metrics, which the
Prometheus chart installs. The drift job pushes `data_drift_share`,
`data_drift_score{column}`, `data_drift_samples`,
`data_drift_columns` and `data_drift_last_run_timestamp_seconds` to the
PushGateway, which Prometheus scrapes with `honor_labels: true` — without that
the column name on each score would be overwritten.

### Logs

Every service writes **one JSON object per line** to stdout. Grafana Alloy runs
as a DaemonSet, reads the pods on its own node and sends the lines to Loki with
four labels: `namespace`, `app`, `pod`, `container`.

```json
{"ts": "2026-09-20T20:00:23.796Z", "level": "info", "event": "prediction",
 "service": "inference", "request_id": "...", "model_version": "1",
 "features": {"MedInc": 8.32, "...": 0}, "prediction": 4.13, "latency_ms": 4.6}
```

Events: `startup`, `model_loaded`, `checksum_mismatch`, `model_load_failed`,
`request`, `prediction`, `validation_error` (field names only, never the
values), `rate_limited`, `fault_injected`, `internal_error`. The uvicorn access
log is off, because the service logs its own requests as JSON.

Useful LogQL:

```logql
{namespace="production", app="inference"} | json | level="error"
{app="registry-ops"} | json | event="model_registry_audit"
{namespace="production", app="inference"} | json | event="prediction"
```

The last one is also what the drift job reads: the features are already in
Loki, so nothing has to store a second copy of them.

### Dashboards

Three, provisioned from Git as ConfigMaps built by kustomize
(`gitops/apps/grafana-dashboards/`) and picked up by the Grafana sidecar.
`allowUiUpdates: false` — a change made in the browser is thrown away on the
next restart, which is the point.

| Dashboard | Panels |
|---|---|
| **Inference** | request rate, p50/p95 latency, error rate — all split by `model_version` and namespace — pod CPU and memory, rate-limited and validation-error counts, and a live log panel from Loki |
| **Model quality** | drifted share, PSI per column, sample count, time of the last run, and the registry audit lines from Loki |
| **Cost** | the OpenCost metrics: what the cluster and each namespace cost per hour |

### Alerts

Four rules, evaluated and sent by Grafana itself (no Alertmanager), provisioned
from `gitops/apps/grafana/values.yaml`. Each one links to the matching section
of the runbook.

| Alert | Severity | Condition |
|---|---|---|
| Inference p95 latency is too high | warning | p95 > 250 ms in `production` for 5 min |
| Inference is returning server errors | critical | 5xx share > 1 % for 5 min |
| The live data no longer looks like the training data | warning | drifted share > 0.25 for 5 min |
| The drift job has not run for two hours | warning | last run older than 2 h |

The drift rule was seen going from Normal to **Firing** on the running cluster
after 6000 drifted requests: `max(data_drift_share)` reached 0.375 against the
threshold of 0.25, and it returned to Normal when normal traffic came back.

The contact point is a **placeholder address** and no SMTP server is
configured, so nothing is actually delivered; alerts are visible in the Grafana
UI. See [`docs/escalation-policy.md`](docs/escalation-policy.md) for who would
be notified and how fast.

## Model registry and promotion

The registered model is `california-housing`. Every training run creates a new
version, and every version carries the same seven tags:

| Tag | What it is |
|---|---|
| `git_sha` | the commit the training image was built from |
| `dataset_sha256` | SHA-256 of the dataset CSV, so the data version is pinned too |
| `model_sha256` | SHA-256 of the serialized model file inside the artifact |
| `rmse`, `mae`, `r2` | the metrics on the test split |
| `run_id` | the MLflow run that produced it |

That is the whole traceability chain: a pod says which version it serves, the
version says which commit and which data it came from, and the run holds the
parameters.

**Aliases are what the code reads; stages are set as well** because the
assignment describes the workflow in those words and the MLflow UI shows them:

| Alias | Stage | Meaning |
|---|---|---|
| `staging` | `Staging` | the newest trained version. Set by the training job. |
| `production` | `Production` | what the production pods load. |
| `previous-production` | `Archived` | the version production used before the last change — the rollback target. |

### The promotion workflow

```
train (workflow)  →  version N, alias staging  →  staging pods load it in <60s
                                                         │
                          you check it                   ▼
                  edit modelVersion + modelSha256 in gitops/envs/production.yaml
                                     │
                                  git push
                                     │
                       Argo CD sync → Argo Rollouts canary
                                     │  10% → pause → 50% → pause → 100%
                                     ▼
                      PostSync hook: registry_ops sync --production-version N
                          alias production → N, stage Production
                          previous version → Archived, alias previous-production
                          one JSON audit line → Loki
```

The hook is `PostSync` and not `PreSync` on purpose. Argo CD runs `PostSync`
hooks only once the Application is Healthy, and for a `Rollout` that means the
canary finished. So the registry says "Production" when the version really
serves all the traffic — and if the canary was aborted the hook never runs and
the registry keeps naming the old version, which is the truth.

Full instructions with the commands: [`RUNBOOK.md`](RUNBOOK.md#roll-out-a-new-model-version).

## Deployment strategy

**Canary with Argo Rollouts, replica based, with automatic abort.** Production
runs 10 pods; the steps are `10% → pause 2 min → 50% → pause 2 min → 100%`.
There is no traffic router: one `ClusterIP` Service sits in front of all pods
of the release, so "10 %" is one new pod next to nine old ones. `maxSurge: 1`
and `maxUnavailable: 0` keep that step honest.

A background `AnalysisTemplate` asks Prometheus every 30 seconds for the 5xx
share of the **new** version only. Three failed measurements in a row abort the
rollout and the old pods take everything back. 4xx is excluded on purpose: bad
JSON from a client is not the new model's fault.

Both halves were measured. A good promotion takes **about five minutes** and
nine measurements. A bad one was aborted **about two minutes after the push**,
after three measurements of 0.548, 0.583 and 0.572 against the limit of 0.05.
Because only one pod of eleven served the bad version, the whole service never
showed more than **2.08 % of 5xx**, for about two minutes.

Staging uses the same chart with `canaryEnabled: false` — a plain rolling
update, because a new model should appear there at once.

Why canary and not Blue-Green or A/B, what it costs, and what would be done
with more time: [`ADR.md`](ADR.md).

To see the automatic abort on purpose, set `faultRate` together with a new
`modelVersion` in `gitops/envs/production.yaml` and commit. `0.5` is what was
really used and is enough: half of the new pod's answers are 500, which is ten
times the limit. `1` works as well. Send traffic while it runs, or the analysis
has nothing to measure and passes. Undo with `git revert`. The whole run, with
the numbers and the screenshots, is in
[`docs/demo-trace.md`](docs/demo-trace.md#7-the-canary-that-aborted-by-itself).

## Rollback

One command:

```bash
git revert <the promotion commit>
git push
```

The values file goes back to the previous `modelVersion` and `modelSha256`,
Argo CD syncs, Argo Rollouts rolls the pods the same careful way, and the
`PostSync` hook moves the registry alias and stage back and archives the
version that was live.

For aborting a canary by hand, and for the manual `registry-ops` escape hatch
when the hook itself failed, see [`RUNBOOK.md`](RUNBOOK.md#roll-back).

## Security baseline

| Requirement | How it is done | Where |
|---|---|---|
| **C1** Input validation | Pydantic v2, `extra="forbid"`, a realistic range per feature; a `RequestValidationError` handler turns 422 into **400** with field names only — no stack trace, no echo of the input | `services/inference/inference/schemas.py`, `app.py` |
| **C2** Rate limiting | `slowapi` on `/predict` only, `RATE_LIMIT` (default `20/second`) per client address, 429 with a clean JSON body; `/metrics`, `/health/*`, `/info` exempt | `services/inference/inference/app.py` |
| **C3** RBAC | three Kubernetes groups — `mlops-engineers`, `viewers`, `stepfunctions-runners` — bound per namespace, mapped from IAM roles by EKS access entries. No role can read a Secret or use `pods/exec` outside staging | [`rbac/`](rbac/README.md), `terraform/modules/eks/` |
| **C4** Immutable artifacts | training tags each version with `model_sha256`; inference downloads, hashes and compares **before** unpickling, and stays at 503 on a mismatch; production pins the same hash in Git; the S3 bucket is versioned | `services/*/model_hash.py`, `gitops/envs/production.yaml`, `terraform/modules/mlflow/` |
| **C5** Audit logging | every registry change prints one `event=model_registry_audit` JSON line with action, version, both stages, actor and commit; Alloy ships it to Loki and a dashboard panel shows it | `services/registry-ops/registry_ops/audit.py` |
| **C6** Threat model | five threats, the control for each and the residual risk | [`docs/threat-model.md`](docs/threat-model.md) |

Beyond the required list: no static AWS credentials anywhere (GitHub OIDC and
EKS Pod Identity), both platform passwords generated by Terraform and never in
Git, `gitleaks` in the pre-commit hooks and as a full scan in CI, Trivy on
every image, ECR scan on push with immutable tags, and every container non-root
with a read-only root filesystem and all capabilities dropped.

## Tests and CI

Every service has its own test suite, and none of them needs a network:

| Component | Tests | Time |
|---|---|---|
| training | 55 | 10 s |
| inference | 115 | 1 s |
| registry-ops | 29 | 15 s |
| drift-monitor | 31 | 3 s |
| lambda | 49 | under 1 s |

```bash
cd services/inference && uv sync --locked && uv run pytest
```

![the four test suites passing](docs/screenshots/03-tests-all-services.png)

### The pipeline

`.github/workflows/final-project-ci.yml`, on `ubuntu-24.04-arm` — free on
public repositories and the same architecture as the cluster.

| Job | What it does |
|---|---|
| `lint` | the same pre-commit hooks that run on the machine |
| `test` | the five test suites above, one job each |
| `terraform` | `scripts/validate_terraform.sh`: fmt, `init -backend=false`, `validate`, both stacks |
| `gitops` | `scripts/validate_gitops.sh`: renders every chart and checks it with kubeconform |
| `build-and-scan` | builds each image, checks it does not run as root, Trivy: HIGH printed, CRITICAL fails |
| `secret-scan` | a full gitleaks scan of `final-project/` and the workflow files |
| `push-images` | pushes the four images to ECR, tagged with the commit SHA — skipped until `FINAL_AWS_ROLE_ARN` is set |

Only `push-images` touches AWS, and it uses OIDC: no access key is stored
anywhere. It skips an image whose tag is already in ECR, because ECR tags are
immutable and a re-run of the same commit must not fail.

![all CI jobs green](docs/screenshots/14-ci-terraform-gitops-green.png)

`push-images` is skipped in this run because the AWS side did not exist yet.

With `FINAL_AWS_ROLE_ARN` set, the last job pushes the four images to ECR through OIDC:

![push-images green with the pushed tag](docs/screenshots/15-ci-push-images-green.png)

### The two validation scripts

They are the same ones CI runs, so a failure can always be reproduced locally:

```bash
final-project/scripts/validate_terraform.sh   # needs terraform only
final-project/scripts/validate_gitops.sh      # needs helm, yq, kustomize, kubeconform
```

`validate_gitops.sh` renders the app-of-apps chart, then reads the list of
charts, versions, value files and parameters **out of the rendered
Applications** — so it checks exactly what Argo CD would deploy and no version
is written down twice. It also checks that every Helm parameter an Application
passes is really a key of the chart it passes it to. It ends with a table of
127 resources across 16 components.

![terraform checks](docs/screenshots/11-validate-terraform.png)

![every rendered component checked](docs/screenshots/12-validate-gitops.png)

### GitLab

`final-project/.gitlab-ci.yml` is the same pipeline written for GitLab, because
the assignment asks for GitLab CI and this project is on GitHub. The `lint`,
`terraform`, `gitops`, `tests` and `secret-scan` jobs were really run with
[gitlab-ci-local](https://github.com/firecow/gitlab-ci-local):

```bash
gitlab-ci-local --file final-project/.gitlab-ci.yml gitops
```

![the new jobs passing under gitlab-ci-local](docs/screenshots/13-gitlab-ci-local-new-jobs.png)

`build-and-scan` needs the docker-in-docker service of a real runner, and
`push-images` and `train` would need AWS to trust GitLab's OIDC provider as
well. Those three are written but untested, and each says so in a comment.

## Run everything locally

The stack in `docker-compose.yml` is the same picture as the cluster, only
smaller: MLflow with a Postgres behind it, two copies of the prediction API and
a PushGateway. The training job, the registry tool and the drift job are in the
profile `tools` and run once with `docker compose run`.

```bash
cd final-project
cp .env.example .env                  # only placeholders, nothing secret
docker compose --profile tools build  # first time only, about 4 minutes
docker compose up -d --wait
```

| What | Address | Note |
|---|---|---|
| MLflow UI and API | <http://localhost:5001> | 5001, because macOS uses 5000 for AirPlay |
| inference, staging | <http://localhost:8001> | follows the alias `staging` |
| inference, production | <http://localhost:8002> | follows the alias `production` |
| PushGateway | <http://localhost:9091> | where the drift job pushes its numbers |

Both API containers start before any model exists. They stay `not ready` (503
on `/health/ready`), keep asking the registry every ten seconds and start
serving as soon as the alias they follow points at a version — exactly what
happens in the cluster at step 6.

Then run the whole story once:

```bash
scripts/local_e2e.sh
```

It trains two versions, promotes one and then the other, rolls back, shows a
refused request (400) and a rate limited one (429), starts a throw-away
container with the wrong checksum to show that it never becomes ready, sends
normal and then drifted traffic, and lets the drift job compare the two. About
two and a half minutes, and it can be run as often as you like.

```bash
python3 scripts/send_traffic.py --mode normal  --count 400 --rate 15 --url http://localhost:8001
python3 scripts/send_traffic.py --mode drift   --count 400 --rate 15 --url http://localhost:8001
python3 scripts/send_traffic.py --mode invalid --count 5   --url http://localhost:8002
python3 scripts/send_traffic.py --mode burst   --count 80  --url http://localhost:8002

curl -X POST localhost:8002/predict -H 'Content-Type: application/json' -d '{
  "MedInc": 8.3252, "HouseAge": 41.0, "AveRooms": 6.9841, "AveBedrms": 1.0238,
  "Population": 322.0, "AveOccup": 2.5556, "Latitude": 37.88, "Longitude": -122.23}'

docker compose down        # keeps the models and the database
docker compose down -v     # removes them as well, for a clean start
```

### What a local run looks like

The stack after `docker compose up -d --wait`:

![the local stack is healthy](docs/screenshots/04-compose-stack-healthy.png)

`scripts/local_e2e.sh` trains two versions, promotes the first one, replaces it
with the second one and then rolls back. Every change of the registry prints
one JSON audit line, and the production API follows within a few seconds:

![training, promotion and rollback](docs/screenshots/05-e2e-train-promote-rollback.png)

Bad input is refused with 400, too many requests with 429, and a model whose
file does not match the pinned checksum is never loaded, so the API stays "not
ready":

![validation, rate limit and checksum check](docs/screenshots/06-e2e-validation-ratelimit-checksum.png)

The drift job finds no drift in normal traffic and finds three moved features
in the second batch. The numbers end up in the PushGateway:

![the drift check](docs/screenshots/07-e2e-drift.png)

The model registry after the run. Version 1 is in production again, version 2
keeps the aliases `staging` and `previous-production`, and every version
carries the Git commit, the dataset hash, the model checksum and the metrics as
tags:

![model versions with aliases and tags](docs/screenshots/08-mlflow-model-versions.png)

![tags and stage of the production version](docs/screenshots/09-mlflow-version-tags.png)

In this local run `git_sha` is `local`, because the images have no Git in them
and the value comes from `.env`. CI and the cluster pass the real commit. Both
versions have the same `model_sha256` because training is deterministic: the
same data and the same parameters give the same file.

### Images

All four are built from `python:3.13-slim`, install their dependencies with
`uv sync --locked` in a first build stage and run as user `10001`. The build
context is always `final-project/`, because the training and drift images ship
a file from `data/`.

| Image | Size (arm64) | Why it is that size |
|---|---|---|
| `registry-ops` | 239 MB | `mlflow-skinny` only, no numpy or pandas |
| `inference` | 591 MB | scipy, pandas and scikit-learn are needed to load the model |
| `training` | 922 MB | the full `mlflow` package on top of that |
| `drift-monitor` | 977 MB | Evidently brings plotly and statsmodels |

```bash
docker build -f services/inference/Dockerfile -t final-project/inference:local .
```

## Code quality

The checks are run by [pre-commit](https://pre-commit.com/). The list of hooks
is in `.pre-commit-config.yaml` in the root of the repository, because
pre-commit only reads it from there. Every hook is limited to this folder, so
the graded homework folders are never touched.

| Hook | What it does |
|---|---|
| pre-commit-hooks | whitespace, end of file, YAML syntax, big files, private keys, merge markers |
| ruff | lints and formats the Python code |
| yamllint | YAML style, configured in `.yamllint` |
| gitleaks | looks for secrets in what is about to be committed |
| terraform fmt | formats the Terraform files |

```bash
cd final-project && uv sync            # once

# from the root of the repository
uv run --project final-project pre-commit install
uv run --project final-project pre-commit run --all-files
```

The commands are run from the root because pre-commit needs to see the whole
repository.

![pre-commit hooks passing](docs/screenshots/01-pre-commit-all-hooks.png)

The same hooks run in GitHub Actions on every push (`final-project-ci`, job
`lint`):

![green lint run in GitHub Actions](docs/screenshots/02-ci-lint-green.png)

## Cost

There is no free tier on this AWS account, so the cluster is created at the
start of a working session and destroyed at the end of it.

| Item | Per hour |
|---|---|
| EKS control plane | $0.10 |
| 2 × `t4g.large` | $0.134 |
| NAT gateway | $0.045 |
| S3, ECR, Lambda, Step Functions, CloudWatch | cents per month |
| **Total** | **about $0.28**, roughly $6.70 a day |

The *Cost* dashboard shows the part of this that OpenCost can see. Measured on
the running cluster: **$0.135 per hour** for the nodes and the EBS volumes,
$3.25 a day, $98.83 a month, with `monitoring` the most expensive namespace at
$0.0195 per hour. OpenCost only prices what runs **inside** the cluster, so the
EKS control plane and the NAT gateway are not in that number — which is why the
table above says $0.28 and the dashboard says $0.135. The dashboard still
answers the question the AWS bill never does: which namespace is expensive.

The cluster is deliberately small, and the resource requests were measured
rather than guessed. Per namespace, read out of the rendered manifests:

| Namespace | CPU requests | Memory requests | Pods |
|---|---|---|---|
| `argocd` | 250m | 896Mi | 5 |
| `mlops-system` | 350m | 1408Mi | 3 |
| `monitoring` | 580m | 2240Mi | 10 |
| `staging` | 100m | 512Mi | 2 |
| `production` | 500m | 2560Mi | 10 |
| short lived: drift job, registry hook, canary surge pod | up to 350m | up to 704Mi | up to 3 |
| **total of the above** | **2130m** | **8320Mi** | **33** |

The two `t4g.large` nodes report **1930m CPU and about 6.9 GiB allocatable
each**, so roughly 3.8 CPUs and 13 GiB for pods in total.

`kubectl describe node` on the running cluster, with 47 pods scheduled:

| Node | CPU requested | Memory requested |
|---|---|---|
| node 1 | 1300m (67 %) | 4822Mi (68 %) |
| node 2 | 1160m (60 %) | 3606Mi (51 %) |

`kube-system` is 12 of those pods and asks for **680m CPU and 812Mi** — CoreDNS,
kube-proxy, the VPC CNI, the EBS CSI driver and the Pod Identity agent. That
row used to be an estimate; these are the real numbers.

Two thirds full is the right place to be here: it leaves room for the canary
surge pod, the drift Job and the registry hook Job without paying for a third
node.

This is why the inference CPU request is `50m` in both `envs/` files and not
the `100m` of the chart default: at `100m` the two inference namespaces alone
would ask for 1.3 CPU — a third of the cluster — for pods that answer in about
5 ms.

## Teardown

**The order matters.** Argo CD created the volumes, not Terraform, so Terraform
cannot delete them. And if Argo CD is removed first, nothing is left to process
the finalizers on its Applications, so the namespace hangs in `Terminating` for
ever.

There is one trap in the middle. Deleting the root Application does remove
every child Application and every workload, but it does **not** remove the two
volume claims that a StatefulSet created for itself: `data-postgres-0` in
`mlops-system` and `storage-loki-0` in `monitoring`. Argo CD never created
those two objects, so it does not prune them, and each one holds an EBS volume
that keeps costing money after the cluster is gone. Delete them by hand.

```bash
# 1. Delete the root Application. Its finalizer removes every child
#    Application and every workload with it.
kubectl -n argocd delete application mlops-platform

# 2. Wait until no Application is left. Two or three minutes.
kubectl -n argocd get applications

# 3. Delete the two volume claims the StatefulSets made. Argo CD does not.
kubectl delete pvc --all -n mlops-system
kubectl delete pvc --all -n monitoring

# 4. Wait until the EBS volumes are really gone. This must print nothing.
kubectl get pv

# 5. The platform stack.
cd final-project/terraform/stacks/platform && terraform destroy

# 6. The infra stack, last: it deletes the cluster the platform stack used.
cd ../infra && terraform destroy
```

Then check that nothing is left, because a resource created from inside the
cluster is in no Terraform state:

```bash
export AWS_PROFILE=goit
aws eks list-clusters --region us-east-1
aws ec2 describe-volumes --region us-east-1 --query 'Volumes[].VolumeId'
aws ec2 describe-nat-gateways --region us-east-1 \
  --filter Name=state,Values=available --query 'NatGateways[].NatGatewayId'
aws elbv2 describe-load-balancers --region us-east-1 \
  --query 'LoadBalancers[].LoadBalancerArn'
```

All four should come back empty. What to do when a namespace still hangs is in
[`RUNBOOK.md`](RUNBOOK.md#teardown).

The Terraform state bucket is kept on purpose and is not managed by Terraform.

## Documents

| Document | What is in it |
|---|---|
| [`RUNBOOK.md`](RUNBOOK.md) | rolling out a model, rolling back, and twelve incidents with exact commands |
| [`ADR.md`](ADR.md) | why canary, what it costs, what would be done differently |
| [`docs/demo-trace.md`](docs/demo-trace.md) | the whole demo on the real cluster, with the measured numbers |
| [`docs/threat-model.md`](docs/threat-model.md) | five threats, the control for each, the residual risk |
| [`docs/escalation-policy.md`](docs/escalation-policy.md) | which alert goes to whom, and how fast |
| [`terraform/README.md`](terraform/README.md) | the two stacks, the modules, apply and destroy |
| [`gitops/README.md`](gitops/README.md) | the app of apps, the sync waves, every component |
| [`gitops/charts/inference/README.md`](gitops/charts/inference/README.md) | the canary chart in detail |
| [`gitops/charts/drift-monitor/README.md`](gitops/charts/drift-monitor/README.md) | the drift CronJob |
| [`rbac/README.md`](rbac/README.md) | the three groups and the permission matrix |
| [`lambda/README.md`](lambda/README.md) | the two Lambda handlers and the pipeline input |
| [`data/README.md`](data/README.md) | where the dataset came from and how the reference sample was made |
| `services/*/README.md` | each service: settings, endpoints, metrics, log events |
