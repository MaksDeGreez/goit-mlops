# Final project — an MLOps platform on AWS

An MLOps platform built on AWS EKS. Terraform creates the infrastructure, Argo CD deploys
everything that runs in the cluster, and a self-hosted MLflow server with a Model Registry keeps
the experiments and the model versions. The model itself is a simple scikit-learn regression on
the California Housing dataset and is served by a FastAPI service. New versions go out as canary
releases with Argo Rollouts. Prometheus, Grafana and Loki collect metrics and logs, Evidently
checks the input data for drift, and GitHub Actions runs the CI pipeline.

**Status: work in progress.** The four services, their images and the whole local stack are done
and can be run end to end on one machine. The infrastructure (Terraform, Argo CD, the cluster) is
not written yet. Every section below says clearly what is already there.

## Services

Four small Python services, each with its own dependencies, tests, Dockerfile and README.

| Service | What it does |
|---|---|
| [`services/training`](services/training/README.md) | trains the model and writes a new version into the MLflow Model Registry |
| [`services/inference`](services/inference/README.md) | FastAPI service that serves one version of the model |
| [`services/registry-ops`](services/registry-ops/README.md) | promotes, rolls back and deletes model versions, and writes an audit line for every change |
| [`services/drift-monitor`](services/drift-monitor/README.md) | compares the live features with the training data and pushes the result to Prometheus |

All four images are built from `python:3.13-slim`, install their dependencies with `uv sync
--locked` in a first build stage and run as user `10001`. The build context is always this folder,
because the training and drift images ship a file from `data/`.

| Image | Size (arm64) | Why it is that size |
|---|---|---|
| `registry-ops` | 239 MB | `mlflow-skinny` only, no numpy or pandas |
| `inference` | 591 MB | scipy, pandas and scikit-learn are needed to load the model |
| `training` | 922 MB | the full `mlflow` package on top of that |
| `drift-monitor` | 977 MB | Evidently brings plotly and statsmodels |

```bash
docker build -f services/inference/Dockerfile -t final-project/inference:local .
```

## Run everything locally

The stack in `docker-compose.yml` is the same picture as the cluster, only smaller: MLflow with a
Postgres behind it, two copies of the prediction API and a PushGateway. The training job, the
registry tool and the drift job are in the profile `tools` and run once with `docker compose run`.

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
| Postgres | not published | only MLflow talks to it |

Both API containers start before any model exists. They stay `not ready` (503 on
`/health/ready`), keep asking the registry every ten seconds and start serving as soon as the alias
they follow points at a version.

Then run the whole story once:

```bash
scripts/local_e2e.sh
```

It trains two versions, promotes one and then the other, rolls back, shows a refused request (400)
and a rate limited one (429), starts a throw-away container with the wrong checksum to show that it
never becomes ready, sends normal and then drifted traffic, and lets the drift job compare the two.
It takes about two and a half minutes and can be run as often as you like.

The traffic generator can also be used on its own. It needs nothing but Python:

```bash
python3 scripts/send_traffic.py --mode normal  --count 400 --rate 15 --url http://localhost:8001
python3 scripts/send_traffic.py --mode drift   --count 400 --rate 15 --url http://localhost:8001
python3 scripts/send_traffic.py --mode invalid --count 5   --url http://localhost:8002
python3 scripts/send_traffic.py --mode burst   --count 80  --url http://localhost:8002
```

One prediction by hand:

```bash
curl -X POST localhost:8002/predict -H 'Content-Type: application/json' -d '{
  "MedInc": 8.3252, "HouseAge": 41.0, "AveRooms": 6.9841, "AveBedrms": 1.0238,
  "Population": 322.0, "AveOccup": 2.5556, "Latitude": 37.88, "Longitude": -122.23}'

curl localhost:8002/info
curl localhost:8001/metrics | grep inference_
docker compose run --rm registry-ops list
```

Stopping it:

```bash
docker compose down        # keeps the models and the database
docker compose down -v     # removes them as well, for a clean start
```

MLflow needs about 1.6 GB of memory with one worker, which is by far the largest part of the stack;
the two API containers use about 165 MB each.

## Tests

Every service has its own test suite and they all run without a network:

```bash
cd services/inference && uv sync --locked && uv run pytest
```

| Service | Tests | Time |
|---|---|---|
| training | 55 | 10 s |
| inference | 115 | 1 s |
| registry-ops | 29 | 15 s |
| drift-monitor | 31 | 3 s |

## CI pipeline

The pipeline is `.github/workflows/final-project-ci.yml`, in the root of the repository, because
GitHub only reads workflows from there. It runs on `ubuntu-24.04-arm`, the same architecture as the
development machine and the cluster, and it needs no AWS access.

| Job | What it does |
|---|---|
| `lint` | the same pre-commit hooks that run on the machine |
| `test` | the tests of the four services, one job each |
| `build-and-scan` | builds each image, checks that it does not run as root, then Trivy: HIGH findings are printed, a CRITICAL one fails the job |
| `secret-scan` | a full gitleaks scan of `final-project/` and of the workflow files |

The images are not pushed anywhere yet. That step is added together with the ECR repositories.

`final-project/.gitlab-ci.yml` is the same pipeline written for GitLab, because the assignment asks
for GitLab CI and this project is on GitHub. The `lint`, `test` and `secret-scan` jobs were really
run with [gitlab-ci-local](https://github.com/firecow/gitlab-ci-local):

```bash
gitlab-ci-local --file final-project/.gitlab-ci.yml secret-scan
```

`build-and-scan` needs the docker-in-docker service of a GitLab runner, which gitlab-ci-local
cannot start, so that one job is written but untested. It is marked as such in the file.

## Structure

`[done]` is in the repository, `[planned]` is not written yet.

```
final-project/
├── terraform/                  # [planned]
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
├── services/                   # [done]
│   ├── inference/              # FastAPI service that serves the model
│   ├── training/               # training job, writes to the MLflow registry
│   ├── registry-ops/           # promote, roll back and delete model versions
│   └── drift-monitor/          # Evidently job that looks for data drift
├── scripts/                    # [done] dataset snapshot, traffic, local end to end
├── lambda/                     # [planned] Lambda functions of the training pipeline
├── gitops/                     # [planned] everything Argo CD deploys
├── rbac/                       # [planned] roles for mlops-engineer and viewer
├── data/                       # [done] California Housing snapshot and reference data
├── docs/                       # [done] screenshots; diagrams and threat model to come
├── docker-compose.yml          # [done] the local end-to-end stack
├── .gitlab-ci.yml              # [done] the CI pipeline written for GitLab
├── pyproject.toml              # [done] Python version and the tools used for checks
├── README.md
├── RUNBOOK.md                  # [planned] how to run and operate the platform
└── ADR.md                      # [planned] the decisions taken and why
```

Terraform will keep its state in S3, so it does not depend on the branch that is checked out.

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

All hooks passing locally:

![pre-commit hooks passing](docs/screenshots/01-pre-commit-all-hooks.png)

The same hooks run in GitHub Actions on every push (`final-project-ci`, job `lint`):

![green lint run in GitHub Actions](docs/screenshots/02-ci-lint-green.png)

## Requirements

| Tool | Version | Used for |
|---|---|---|
| uv | 0.8 or newer | Python version and tools |
| Terraform | 1.5 or newer | creating the infrastructure |
| AWS CLI | 2.x | access to the account |
| kubectl | 1.30 or newer | working with the cluster |
| Helm | 3 or newer | checking charts before Argo CD syncs them |
| Docker | any | building the service images |
