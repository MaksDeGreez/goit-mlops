# Final project — an MLOps platform on AWS

An MLOps platform built on AWS EKS. Terraform creates the infrastructure, Argo CD deploys
everything that runs in the cluster, and a self-hosted MLflow server with a Model Registry keeps
the experiments and the model versions. The model itself is a simple scikit-learn regression on
the California Housing dataset and is served by a FastAPI service. New versions go out as canary
releases with Argo Rollouts. Prometheus, Grafana and Loki collect metrics and logs, Evidently
checks the input data for drift, and GitHub Actions runs the CI pipeline.

**Status: work in progress.** Only the repository layout and the code quality checks are in place
so far. The parts described below are added step by step.

## Planned structure

```
final-project/
├── terraform/
│   ├── modules/
│   │   ├── vpc/                # network: subnets, NAT, routing
│   │   ├── eks/                # the cluster, node group and add-ons
│   │   ├── argocd/             # Argo CD and the root Application
│   │   ├── mlflow/             # S3 bucket and database for MLflow
│   │   ├── monitoring/         # what monitoring needs from AWS
│   │   └── training-pipeline/  # Step Functions, Lambda, ECR
│   └── stacks/
│       ├── infra/              # stack 1: network and cluster
│       └── platform/           # stack 2: everything on top of the cluster
├── services/
│   ├── inference/              # FastAPI service that serves the model
│   ├── training/               # training job, writes to the MLflow registry
│   ├── registry-ops/           # promote, roll back and delete model versions
│   └── drift-monitor/          # Evidently job that looks for data drift
├── lambda/                     # Lambda functions of the training pipeline
├── gitops/                     # everything Argo CD deploys: apps, values, charts
├── rbac/                       # Kubernetes roles for mlops-engineer and viewer
├── data/                       # California Housing snapshot and reference data
├── docs/                       # screenshots, diagrams, threat model, escalation policy
├── .gitlab-ci.yml              # the CI pipeline written for GitLab
├── pyproject.toml              # Python version and the tools used for checks
├── README.md
├── RUNBOOK.md                  # how to run and operate the platform
└── ADR.md                      # the decisions taken and why
```

Terraform keeps its state in S3, so it does not depend on the branch that is checked out.

The GitHub Actions workflow is at **`.github/workflows/final-project-ci.yml`** in the root of the
repository. GitHub only reads workflows from that folder, so it cannot live here.

## Code quality

The checks are run by [pre-commit](https://pre-commit.com/). The list of hooks is in
`.pre-commit-config.yaml` in the root of the repository, because pre-commit only reads it from
there. Every hook is limited to this folder, so the graded homework folders are never touched.

| Hook | What it does |
|---|---|
| pre-commit-hooks | whitespace, end of file, YAML syntax, big files, private keys, merge markers |
| ruff | lints and formats the Python code |
| yamllint | YAML style, configured in `.yamllint` |
| gitleaks | looks for secrets in what is about to be committed |
| terraform fmt | formats the Terraform files |

Install the Python tools once:

```bash
cd final-project
uv sync
```

Then, from the root of the repository:

```bash
# install the git hook, so the checks run on every commit
uv run --project final-project pre-commit install

# run every check on every file
uv run --project final-project pre-commit run --all-files
```

The commands are run from the root because pre-commit needs to see the whole repository.

## Requirements

| Tool | Version | Used for |
|---|---|---|
| uv | 0.8 or newer | Python version and tools |
| Terraform | 1.5 or newer | creating the infrastructure |
| AWS CLI | 2.x | access to the account |
| kubectl | 1.30 or newer | working with the cluster |
| Helm | 3 or newer | checking charts before Argo CD syncs them |
| Docker | any | building the service images |
