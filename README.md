# goit-mlops

Homework and the final project of the MLOps course (GoIT, Neoversity).

Every piece of work has its own folder. Each one also has its own branch with the same name, which
is the branch that was handed in.

| Folder | What it is |
|---|---|
| [`lesson-3/`](lesson-3/) | Homework 1: a setup script, a TorchScript model and two Docker images, a large one and a small one |
| [`lesson-5/`](lesson-5/) | Homework 2: a VPC and an EKS cluster with Terraform |
| [`lesson-7/`](lesson-7/) | Homework 3: Argo CD installed by Terraform, and a GitOps repository |
| [`lesson-9/`](lesson-9/) | Homework 4: MLflow, MinIO, PostgreSQL, PushGateway and Grafana deployed by Argo CD |
| [`lesson-10/`](lesson-10/) | Homework 5: a training pipeline with Step Functions, Lambda and CI |
| [`final-project/`](final-project/) | **The final project**: an MLOps platform on AWS EKS |

## The final project

Start with [`final-project/README.md`](final-project/README.md). It has the architecture, the steps
to deploy everything from zero, and the description of every part.

| Document | What is in it |
|---|---|
| [README](final-project/README.md) | architecture, deployment, namespaces, monitoring, model registry, security, cost, teardown |
| [Demo trace](final-project/docs/demo-trace.md) | screenshots of the real deployment, from the cluster to the rollback |
| [RUNBOOK](final-project/RUNBOOK.md) | how to release a model, roll back, and what to do when an alert fires |
| [ADR](final-project/ADR.md) | why the canary strategy was chosen and what it costs |
| [Threat model](final-project/docs/threat-model.md) | five threats and the controls against them |
| [Escalation policy](final-project/docs/escalation-policy.md) | which alert goes to whom |

The workflows of the final project are in [`.github/workflows/`](.github/workflows/), because GitHub
only reads them from there: `final-project-ci.yml` and `final-project-train.yml`.
