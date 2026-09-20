# Threat model

One page on what an attacker could go after in this system, and what stops
them. It covers this project only, not AWS or Kubernetes in general.

## Assets

| Asset | Why it matters |
|---|---|
| The model artifact in S3 | It is a pickle. Loading one runs code. |
| The MLflow Model Registry | It decides which version production serves. |
| The prediction API | The only thing that answers requests. |
| AWS credentials and the two generated passwords | Full access to the account or to the platform. |
| The Git repository | It is the only source of truth for what is deployed. |

## Trust boundaries

```
public internet ──► GitHub (public repo, Actions)
                      │ OIDC, no stored keys
                      ▼
                    AWS account ──► ECR, S3, Step Functions, Lambda
                      │
                      ▼
                    EKS cluster (private nodes, no public service)
                      │  namespaces: staging | production | mlops-system | monitoring | argocd
                      ▼
                    a person with kubectl and an IAM role
```

Three boundaries matter:

1. **GitHub → AWS.** Crossed by a short-lived OIDC token, only from branch
   `final-project` of one repository.
2. **AWS → cluster.** Crossed by EKS access entries: an IAM role maps to a
   Kubernetes group, and the group's rights are the files in `rbac/`.
3. **Outside → cluster.** Not crossed at all. Every Service is `ClusterIP` and
   the nodes are in private subnets. The only way in is `kubectl port-forward`,
   which needs an IAM role first.

## Five threats

### 1. A tampered model artifact runs code inside the cluster

A scikit-learn model is a pickle file. Anyone who can replace the file in S3,
or add a version to the registry, gets code execution in every inference pod.

**Controls.** Training records the SHA-256 of the serialized model file as the
model version tag `model_sha256`
(`services/training/training/registry.py`). Inference downloads the version,
hashes the same file and compares it **before** deserializing
(`services/inference/inference/model_store.py`, `model_hash.py`). On a
mismatch it logs `event=checksum_mismatch`, increments
`inference_model_load_failures_total{reason="checksum_mismatch"}` and stays at
503 on `/health/ready`, so Kubernetes never sends it traffic and Argo Rollouts
aborts the canary. Production pins the same hash a second time in Git
(`modelSha256` in `gitops/envs/production.yaml`), so the registry alone is not
trusted. The artifact bucket has versioning on
(`terraform/modules/mlflow/main.tf`), so an overwrite can be undone.

**Residual risk.** A person who can change both the registry tag and the Git
file can still push a bad model. Both actions leave a trail: the Git commit and
the audit line in Loki.

### 2. Abuse or denial of service on the prediction endpoint

`/predict` deserializes JSON and runs a model. A flood of requests, or huge
values, costs CPU on a cluster that has very little of it.

**Controls.** Every field is a Pydantic v2 model with `extra="forbid"` and a
realistic range per feature (`services/inference/inference/schemas.py`), so bad
input is refused before any work happens, with HTTP 400 and field names only —
no stack trace, no echo of the input. `slowapi` limits `/predict` to
`RATE_LIMIT` (default `20/second`) per client address and answers 429;
`/metrics`, `/health/*` and `/info` are exempt. Requests and rate limiting are
counted in Prometheus and a Grafana rule fires on more than 1 % of 5xx.

**Residual risk, stated honestly.** The rate limit is per pod and lives in the
memory of that pod. With 10 replicas behind one Service the effective limit is
ten times the configured one, and a restart forgets everything. A real
deployment would put the limit in a shared store or in front of the service.
The endpoint is not public here, which is what keeps this acceptable.

### 3. Leaked credentials

A public repository is the easiest place to lose a key.

**Controls.** There is no static AWS key anywhere. GitHub Actions assumes a
role through OIDC, and the trust policy allows only
`repo:MaksDeGreez/goit-mlops:ref:refs/heads/final-project` (both the documented
and the numeric-id form of the claim), with a least-privilege policy: push to
four ECR repositories and start or read one state machine
(`terraform/modules/ci-access/main.tf`). MLflow reaches S3 with EKS Pod
Identity, not with keys. The Postgres and Grafana passwords are
`random_password` resources written straight into Kubernetes Secrets; no file
in Git ever holds them, and nobody's RBAC role can read a Secret
(`rbac/README.md`). `gitleaks` runs as a pre-commit hook on every commit and as
a full scan of `final-project/` and `.github/workflows/` in CI. The Terraform
state bucket is private, versioned and encrypted, and the ECR registry host is
injected at apply time so the account id is never written down.

**Residual risk.** The Terraform state file holds the generated passwords in
clear text. It is in a private, encrypted, versioned bucket, and anyone who can
read it could read the cluster Secrets anyway.

### 4. An unauthorised or silent change to the model registry

Someone points the `production` alias at a bad version, or deletes the version
that is live.

**Controls.** Only `registry-ops` changes the registry, and every state change
prints exactly one JSON line `event=model_registry_audit` with the action, the
version, both stages, the actor and the Git commit
(`services/registry-ops/registry_ops/audit.py`). Alloy ships that line to Loki,
where it stays searchable and is shown on the model quality dashboard. The
normal path is not a command at all: production changes because a commit
changed `modelVersion`, and a `PostSync` hook Job then makes the registry
agree, with `ACTOR=argocd` and `GIT_SHA` set to the commit Argo CD synced.
`delete` refuses to remove the version that is currently in production. In the
cluster, `mlops-engineers` have full rights in `staging` but read-only in
`production`; the only write they keep there is `patch` on `rollouts/status`,
which aborts a canary and cannot change what is deployed.

**Residual risk.** Anyone with the MLflow UI open through a port-forward can
change an alias by hand. It would be logged by MLflow but not as an audit line,
and Argo CD would undo it on the next sync of the hook. MLflow has no login of
its own — that is the reason it is not public.

### 5. Supply chain: images and dependencies

Four images are built from `python:3.13-slim` and pull a few hundred packages.

**Controls.** Every service has a committed `uv.lock`, and CI installs with
`uv sync --locked`, which fails if the lock does not match. Every chart version
is pinned in `gitops/bootstrap/values.yaml`; every GitHub Action is pinned to a
tag; the tools the `gitops` CI job downloads are pinned and their SHA-256 is
verified. Trivy scans each image in CI: HIGH findings are printed, a CRITICAL
one fails the build. ECR scans on push as well, tags are **immutable**, and CI
tags every image with the full commit SHA, so a tag can never quietly change
under a running pod. The containers run as user 10001, non-root, with a
read-only root filesystem, all capabilities dropped and only `/tmp` writable.

**Residual risk.** The images are not signed, and nothing in the cluster checks
where an image came from beyond the registry it is pulled from. An attacker
with ECR push rights could add a new tag; they could not change an existing
one.

## Summary

| Threat | Main control | Where it lives |
|---|---|---|
| Tampered model artifact | SHA-256 checked before unpickling, hash pinned in Git, bucket versioning | `services/inference/inference/model_hash.py`, `gitops/envs/production.yaml` |
| Abuse of `/predict` | Pydantic validation → 400, slowapi → 429 | `services/inference/inference/schemas.py`, `app.py` |
| Leaked credentials | OIDC and Pod Identity instead of keys, gitleaks, generated secrets | `terraform/modules/ci-access/`, `.pre-commit-config.yaml`, CI `secret-scan` |
| Silent registry change | Audit line in Loki, promotion only through Git, RBAC | `services/registry-ops/registry_ops/audit.py`, `rbac/` |
| Supply chain | Locked dependencies, pinned charts and actions, Trivy, immutable tags, non-root | `uv.lock` files, `gitops/bootstrap/values.yaml`, `terraform/modules/ecr/` |
