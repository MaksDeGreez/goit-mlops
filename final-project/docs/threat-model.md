# Threat model

One page on what an attacker could go after in this system, and what stops
them. It covers this project only, not AWS or Kubernetes in general.

**Assets.** The model artifact in S3 (it is a pickle, so loading one runs
code); the MLflow Model Registry, which decides what production serves; the
prediction API; the AWS credentials and the two generated passwords; the Git
repository, the only source of truth for what is deployed.

**Trust boundaries.** GitHub reaches AWS with a short-lived OIDC token, only
from branch `final-project` of one repository. AWS reaches the cluster through
EKS access entries: an IAM role maps to a Kubernetes group, and the group's
rights are the files in `rbac/`. The internet does not reach the cluster at
all: every Service is `ClusterIP`, the nodes are in private subnets, and the
only way in is `kubectl port-forward`, which needs an IAM role first.

## 1. A tampered model artifact runs code inside the cluster

A scikit-learn model is a pickle file. Anyone who can replace it in S3, or add
a version to the registry, gets code execution in every inference pod.

**Controls.** Training records the SHA-256 of the model file as the version tag
`model_sha256` (`services/training/training/registry.py`). Inference hashes the
same file and compares it before deserializing
(`services/inference/inference/model_store.py`, `model_hash.py`). On a mismatch
it logs `event=checksum_mismatch`, counts
`inference_model_load_failures_total{reason="checksum_mismatch"}` and keeps
`/health/ready` at 503, so no traffic reaches it and the canary aborts.
Production pins the same hash a second time in Git (`modelSha256` in
`gitops/envs/production.yaml`). The artifact bucket has versioning on
(`terraform/modules/mlflow/main.tf`), so an overwrite can be undone.

**Residual risk.** Someone who changes both the registry tag and the Git file
can still push a bad model. Both actions leave a trail: the commit and the
audit line in Loki.

## 2. Abuse or denial of service on the prediction endpoint

`/predict` reads JSON and runs a model. A flood of requests costs CPU on a
cluster that has very little of it.

**Controls.** Input is a Pydantic v2 model with `extra="forbid"` and a
realistic range per feature (`services/inference/inference/schemas.py`). Bad
input is refused with HTTP 400 and field names only: no stack trace, no echo of
the input. `slowapi` limits `/predict` to `RATE_LIMIT` (default `20/second`)
per client address and answers 429; `/metrics`, `/health/*` and `/info` are
exempt. A Grafana rule fires on more than 1 % of 5xx. Tested on the running
cluster: 20 requests with a missing field gave 20 × 400, and a burst of 3000
gave 2976 × 200 and 24 × 429.

**Residual risk.** The limit is per pod and lives in that pod's memory, so with
10 replicas the real limit is about 200 requests a second, and a restart
forgets everything. The endpoint is not public, which keeps this acceptable.

## 3. Leaked credentials

A public repository is the easiest place to lose a key.

**Controls.** There is no static AWS key anywhere. GitHub Actions assumes a
role through OIDC, and the trust policy allows only
`repo:MaksDeGreez/goit-mlops:ref:refs/heads/final-project`. Its permissions are
least privilege: push to four ECR repositories, start or read one state machine
(`terraform/modules/ci-access/main.tf`). MLflow reaches S3 with EKS Pod
Identity. The two platform passwords are `random_password` resources written
straight into Kubernetes Secrets, and no RBAC role can read a Secret
(`rbac/README.md`). `gitleaks` runs as a pre-commit hook and as a full CI scan.
The ECR registry host is injected at apply time, so the account id is never
written into Git.

**Residual risk.** The Terraform state file holds those passwords in clear
text. It sits in a private, encrypted, versioned bucket, and anyone who can
read it could read the cluster Secrets anyway.

## 4. An unauthorised or silent change to the model registry

Someone points the `production` alias at a bad version, or deletes the version
that is live.

**Controls.** Only `registry-ops` changes the registry, and every change prints
one JSON line `event=model_registry_audit` with the action, the version, both
stages, the actor and the Git commit
(`services/registry-ops/registry_ops/audit.py`). Alloy ships it to Loki, where
it stays searchable and appears on the model quality dashboard. The normal path
is not a command at all: a commit changes `modelVersion`, and a `PostSync` hook
Job makes the registry agree with `ACTOR=argocd`. `delete` refuses to remove
the version that is in production. `mlops-engineers` have full rights in
`staging` but read-only in `production`, where their only write is `patch` on
`rollouts/status`, which aborts a canary and cannot change what is deployed.
`scripts/check_rbac.sh` asked the live cluster 32 of these questions and all 32
answered as written down.

**Residual risk.** Anyone with the MLflow UI open through a port-forward can
move an alias by hand. MLflow logs it, but not as an audit line, and Argo CD
undoes it on the next sync. MLflow has no login of its own, which is why it is
not public.

## 5. Supply chain: images and dependencies

Four images are built from `python:3.13-slim` and pull a few hundred packages.

**Controls.** Every service has a committed `uv.lock` and CI installs with
`uv sync --locked`. Chart versions are pinned in
`gitops/bootstrap/values.yaml`, every GitHub Action is pinned to a tag, and the
tools the `gitops` job downloads are checked against a known SHA-256. Trivy
scans each image: HIGH findings are printed, a CRITICAL one fails the build.
ECR scans on push, tags are immutable (`terraform/modules/ecr/`), and every
image is tagged with the full commit SHA, so a tag cannot change under a
running pod. Containers run as user 10001 with a read-only root filesystem, all
capabilities dropped and only `/tmp` writable.

**Residual risk.** The images are not signed, and nothing checks where an image
came from beyond the registry. An attacker with ECR push rights could add a new
tag, but could not change an existing one.
