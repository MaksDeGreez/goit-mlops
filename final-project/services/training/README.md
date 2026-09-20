# Training service

Trains the California Housing model and writes a new version into the MLflow Model Registry. It is
a batch job, not a server: it runs, prints one line of JSON and exits. Later it is started by the
Step Functions pipeline as a Kubernetes Job.

```bash
uv sync
MLFLOW_TRACKING_URI=http://localhost:5000 uv run python -m training.run
```

## What one run does

1. reads `data/california_housing.csv` and checks the columns, the types and the missing values;
2. computes the SHA256 of the CSV file, which is the dataset version;
3. splits the data 80/20 with a fixed seed;
4. fits the pipeline: clip the long tails, add two ratio features, scale, then a
   `HistGradientBoostingRegressor`;
5. scores the model on the test split: `rmse`, `mae`, `r2`;
6. logs parameters, metrics and the model to MLflow;
7. registers a new model version;
8. downloads that version again, hashes the model file and writes the hash to the tag
   `model_sha256`;
9. gives the version the alias `staging` and the stage `Staging`;
10. prints the result as one JSON object.

## Settings

Every setting is an environment variable and a command line option. The option wins.

| Variable | Option | Default | What it is |
|---|---|---|---|
| `MLFLOW_TRACKING_URI` | `--tracking-uri` | local `./mlruns` | the MLflow server |
| `MODEL_NAME` | `--model-name` | `california-housing` | name in the registry |
| `EXPERIMENT_NAME` | `--experiment-name` | `california-housing` | MLflow experiment |
| `DATA_PATH` | `--data-path` | see below | the CSV snapshot |
| `GIT_SHA` | `--git-sha` | `git rev-parse HEAD`, else `unknown` | the commit of the code |
| `SAMPLE_ROWS` | `--sample-rows` | all rows | train on a small sample |
| | `--test-size` | `0.2` | size of the test split |
| | `--seed` | `42` | seed for the split and the model |
| | `--max-iter` | `200` | boosting iterations |
| | `--learning-rate` | `0.1` | |
| | `--max-leaf-nodes` | `31` | |
| | `--min-samples-leaf` | `20` | |
| | `--l2-regularization` | `0.0` | |

`DATA_PATH` has two defaults, and the first one that exists is used:
`/app/data/california_housing.csv` inside the container (the image is built with `final-project/`
as the build context) and `final-project/data/california_housing.csv` in the repository. So the job
runs in both places without any setting.

## The line the pipeline reads

Only this one line goes to stdout. Every log message goes to stderr, so the output stays easy to
parse. A run that fails exits with code 1 and prints nothing on stdout.

```json
{"event": "training_finished", "model": "california-housing", "version": "2",
 "run_id": "a48c01d7c9af4878b08942e9ae876f46", "rmse": 0.44533490223490724,
 "mae": 0.29471925786448117, "r2": 0.8486555125600524, "git_sha": "039325b...",
 "dataset_sha256": "41f849ea...", "model_sha256": "70d8f5f5..."}
```

`version` is a string, because the same value is also a tag, and tags in MLflow are strings.

## What the model version carries

Every version gets these tags, all of them strings: `git_sha`, `dataset_sha256`, `model_sha256`,
`rmse`, `mae`, `r2`, `run_id`. Together they answer "which code and which data produced this model,
and is the file still the one that was trained?". The git sha and the dataset hash are also run
parameters and run tags, so they can be searched in the MLflow UI.

The new version always becomes the `staging` one:

* **alias `staging`** — this is what the services actually use, and it always points at the newest
  version;
* **stage `Staging`** — the old MLflow field. It is deprecated and MLflow raises a `FutureWarning`,
  which the code hides for that one call. It is set because the assignment describes the workflow
  with stage names and they are visible in the UI.

Moving a version to production, archiving the one before it and rolling back is not this service's
job: that is `services/registry-ops`.

## How the model is stored

MLflow 3 saves scikit-learn models with the `skops` format by default. That format refuses to save
a `HistGradientBoostingRegressor` or our own transformer unless every type is listed as trusted, so
the job uses the older `cloudpickle` format and the file is called `model.pkl`. The name is never
hard-coded anywhere: it is read from `flavors.sklearn.pickled_model` in the `MLmodel` file.

Because the pipeline contains our own steps, the `training` package is stored inside the model
artifact (`code_paths`). The inference service can therefore load the model without the training
code installed.

`training/model_hash.py` computes the checksum of that file. **The inference service has an
identical copy of this module and of its test.** Training writes the hash, inference recomputes it
after downloading and refuses to serve a model if the two differ. Two copies that drift apart would
look exactly like a changed model file, so they must be kept the same.

Clients set `MLFLOW_ENABLE_PROXY_MULTIPART_DOWNLOAD=false` (done in `training/__init__.py`, before
mlflow is imported). With multipart downloads the client is sent to the object store directly, which
a client outside the cluster cannot reach, and the download then silently writes a file of the right
size filled with spaces.

## Tests

```bash
uv run pytest
```

55 tests, about 10 seconds. The unit tests cover the data checks, every preprocessing function, the
pipeline and the checksum helper. `tests/test_run_integration.py` starts the job as a subprocess
twice against a temporary SQLite-backed MLflow and checks the JSON line, the metrics in the run,
all seven tags, the alias and the stage, that the second run creates version 2 and moves the alias,
that the same data gives the same metrics, and that a missing data file gives exit code 1.

SQLite is used because the plain file store cannot do model versions, aliases or stages. The
artifacts stay in a temporary folder, so running the tests leaves nothing behind.
