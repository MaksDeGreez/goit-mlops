# Inference service

A small FastAPI service that answers with the predicted median house value of one California block
group. It takes the model from the MLflow Model Registry, checks that the file is really the one the
training job produced, and only then loads it.

```bash
uv sync
MLFLOW_TRACKING_URI=http://localhost:5000 uv run python -m inference
```

The service listens on port 8000. In the cluster it runs in the namespaces `staging` and
`production`, with about ten pods during a canary rollout.

## Settings

Everything comes from environment variables, because Kubernetes is the only thing that starts this
service. A value that cannot be used stops the process at once, with a clear message.

| Variable | Default | What it is |
|---|---|---|
| `MLFLOW_TRACKING_URI` | local `./mlruns` | the MLflow server |
| `MODEL_NAME` | `california-housing` | name in the registry |
| `MODEL_ALIAS` | `staging` | follow this alias and reload when it moves |
| `MODEL_VERSION` | not set | pin one version; it wins over `MODEL_ALIAS` |
| `MODEL_SHA256` | not set | extra checksum that must match as well |
| `MODEL_RELOAD_SECONDS` | `60` | how often the alias is checked |
| `RATE_LIMIT` | `20/second` | limit for `/predict`, per client address |
| `FAULT_RATE` | `0` | share of `/predict` calls that fail on purpose |
| `LOG_LEVEL` | `INFO` | |
| `PORT` | `8000` | |

`MODEL_ALIAS` and `MODEL_VERSION` are the two ways to choose a model:

* **alias** — staging follows the alias `staging`, so every new training run is served a minute
  later without any deployment;
* **version** — production pins the number in git. The pinned version never changes under the pod,
  and `MODEL_SHA256` can pin the file as well.

## The API

| Method | Path | What it does |
|---|---|---|
| `POST` | `/predict` | one prediction |
| `GET` | `/health/live` | the process is running |
| `GET` | `/health/ready` | 200 only when a checked model is loaded, else 503 |
| `GET` | `/info` | which model this pod serves |
| `GET` | `/metrics` | Prometheus metrics |

```bash
curl -X POST localhost:8000/predict -H 'Content-Type: application/json' -d '{
  "MedInc": 8.3252, "HouseAge": 41.0, "AveRooms": 6.9841, "AveBedrms": 1.0238,
  "Population": 322.0, "AveOccup": 2.5556, "Latitude": 37.88, "Longitude": -122.23}'
```

```json
{"prediction": 4.636096496311407, "model_name": "california-housing",
 "model_version": "2", "request_id": "6b8921aa51f140de91dd65f4018df3b2"}
```

The prediction is in units of $100,000, the same as the target column of the dataset.

Every answer carries a request id, also in the header `X-Request-ID`. A client can send its own
`X-Request-ID` and find the same id again in the logs.

`/info` is the quickest way to see what a pod is doing:

```json
{"status": "ready", "model_name": "california-housing", "model_version": "2",
 "model_alias": "staging", "model_sha256": "f9123692...", "git_sha": "80842925...",
 "run_id": "0b3edbffe3bf4a56ae0cdf77efb2d86e", "loaded_at": "2026-09-20T20:00:22Z"}
```

## What the service does with the input

All eight features must be there, must be numbers and must be inside the range California really
has. A string like `"8.3"` is refused too: a client that sends text instead of a number has a bug,
and guessing what it meant would hide it. An unknown field is refused as well, because a misspelled
name would otherwise be dropped in silence and the model would quietly use a default.

| Field | Range |
|---|---|
| `MedInc` | 0 – 20 |
| `HouseAge` | 0 – 100 |
| `AveRooms` | above 0, up to 200 |
| `AveBedrms` | above 0, up to 50 |
| `Population` | 1 – 50000 |
| `AveOccup` | above 0, up to 1500 |
| `Latitude` | 32 – 42.5 |
| `Longitude` | -125 – -114 |

## Errors

Bad input gives **400**, not the 422 that FastAPI returns by default, because the rest of the
platform treats 4xx as "the client sent something wrong" and 422 is easy to miss. The answer names
the fields and nothing else — the values that were sent never come back, so a token pasted into the
wrong place is not repeated in a log or an error page.

```json
{"error": "validation_error",
 "detail": [{"field": "MedInc", "message": "Input should be less than or equal to 20"}],
 "request_id": "8f30d22dc2844df6a97cb0901383f196"}
```

| Status | When | Body |
|---|---|---|
| 400 | the input is not valid | field names and short messages |
| 429 | too many requests | `{"error": "rate_limited", ...}` |
| 500 | anything unexpected | only the request id, the cause is in our log |
| 503 | no model is loaded | `{"error": "model_not_ready", ...}` |

A 500 says nothing at all. The traceback goes to the log, where only the team can read it.

## How the model is loaded

1. ask the registry which version the alias points at, or take the pinned one;
2. download that version through the tracking server;
3. read `flavors.sklearn.pickled_model` from the `MLmodel` file, hash that file and compare it with
   the tag `model_sha256` written by the training job, and with `MODEL_SHA256` when it is set;
4. only now deserialize the file and answer requests with it.

Step 4 runs code, because an MLflow scikit-learn model is a pickle. That is the reason for the
order: **the checksum is checked before anything is opened.** When the two hashes differ the service
writes one `checksum_mismatch` line, counts
`inference_model_load_failures_total{reason="checksum_mismatch"}` and keeps running without a model.
`/health/ready` then answers 503 for ever, so Kubernetes sends no traffic to the pod and Argo
Rollouts sees the new version as unhealthy.

`inference/model_hash.py` is a **copy of `services/training/training/model_hash.py`**, together with
its test. The two services compare hashes with each other, so the two copies have to stay identical;
a difference between them would look exactly like a changed model file.

When an alias is used, a background task checks every `MODEL_RELOAD_SECONDS` whether the alias moved
to another version. If it did, the new version goes through the same four steps and is swapped in.
A request that is already running finishes with the old model. If the new version cannot be loaded,
the old one keeps answering and only the error is logged: a broken registry must not take a working
pod down.

The client sets `MLFLOW_ENABLE_PROXY_MULTIPART_DOWNLOAD=false` (in `inference/__init__.py`, before
mlflow is imported). With multipart downloads the client is sent to the object store directly, which
a pod cannot always reach, and the download then silently writes a file of the right size filled
with spaces.

The service uses **`mlflow-skinny`**, the same library without the tracking server and its
dependencies. Downloading a registered version over HTTP and loading it with
`mlflow.sklearn.load_model` both work with it, which was tested against a real
`mlflow server --serve-artifacts`.

## The rate limit

`/predict` is limited with slowapi, keyed by the address of the client. `/metrics`, `/info` and the
health endpoints are never limited, so probes and Prometheus keep working under load.

**The counter lives in the memory of one pod.** With ten pods the cluster therefore allows about ten
times `RATE_LIMIT` in total, and the number resets when a pod restarts. That is good enough here:
the limit exists to keep one broken client from using up a pod, not to sell quotas. A real shared
limit would need Redis or a gateway in front of the service.

## Metrics

`/metrics` has the usual HTTP metrics of `prometheus-fastapi-instrumentator` plus the metrics of this
service:

| Metric | Labels | Why |
|---|---|---|
| `inference_requests_total` | `model_version`, `status_class` | error rate per version |
| `inference_request_duration_seconds` | `model_version` | latency, buckets from 2 ms to 2.5 s |
| `inference_predictions_total` | `model_version` | how much traffic a version really got |
| `inference_prediction_value` | `model_version` | the answers themselves, to see a version go wrong |
| `inference_model_info` | `model_name`, `model_version`, `model_sha256` | always 1, says what is loaded |
| `inference_model_load_failures_total` | `reason` | failed loads, `checksum_mismatch` above all |

Every one of them carries the model version, because during a canary rollout two versions run at the
same time and the analysis that decides "keep going or roll back" has to compare them.

`status_class` is `2xx`, `4xx` or `5xx`. A refused or rate limited request is a client problem and
must not look like a broken service, or the canary would roll back for the wrong reason.

Probes and metric scrapes are not counted at all. They arrive every few seconds and would hide the
real traffic.

## Logs

One JSON object per line on stdout. Loki collects them, and the drift job reads the `prediction`
events back out of Loki, so this format is part of the contract between the services. Every line has
`ts`, `level`, `event`, `service`, `request_id` and `model_version`. The plain text access log of
uvicorn is switched off, because we log the same requests ourselves in a format Loki can parse.

| Event | When |
|---|---|
| `startup` | the process starts, with the settings in it |
| `model_loaded` | a model passed the checksum and is now in use |
| `checksum_mismatch` | the file is not the one that was trained |
| `model_load_failed` | the registry or the download did not work |
| `request` | one request: method, path, status, latency |
| `prediction` | the eight features, the prediction, latency |
| `validation_error` | refused input, **field names only** |
| `rate_limited` | a client went over the limit |
| `fault_injected` | `FAULT_RATE` made this request fail |
| `internal_error` | something we did not think of, with the traceback |

```json
{"ts": "2026-09-20T20:00:22.377Z", "level": "info", "event": "model_loaded", "service": "inference",
 "request_id": null, "model_version": "2", "message": "the model is verified and ready",
 "model_name": "california-housing", "model_alias": "staging", "model_sha256": "f9123692...",
 "git_sha": "80842925...", "run_id": "0b3edbff...", "loaded_at": "2026-09-20T20:00:22Z"}
{"ts": "2026-09-20T20:00:23.796Z", "level": "info", "event": "prediction", "service": "inference",
 "request_id": "6b8921aa51f140de91dd65f4018df3b2", "model_version": "2",
 "features": {"MedInc": 8.3252, "HouseAge": 41.0, "AveRooms": 6.9841, "AveBedrms": 1.0238,
 "Population": 322.0, "AveOccup": 2.5556, "Latitude": 37.88, "Longitude": -122.23},
 "prediction": 4.636096496311407, "latency_ms": 4.83}
{"ts": "2026-09-20T20:00:38.786Z", "level": "error", "event": "checksum_mismatch",
 "service": "inference", "request_id": null, "model_version": "1",
 "message": "the model file of version 1 is not the one that was trained",
 "reason": "checksum_mismatch", "expected": "f9123692...", "pinned": "aaaaaaaa...",
 "actual": "f9123692..."}
```

## The fault switch

`FAULT_RATE` is a demo switch, and it is here on purpose: `FAULT_RATE=1` makes every `/predict` call
answer 500 with the normal generic body. It is the easy way to show that a canary rollout notices a
bad version and rolls it back by itself, without having to train a broken model first. In staging
and production it stays at `0`.

## Numbers from a real run

Measured against a local `mlflow server` with a model trained by `services/training`, on the
development machine (arm64 Mac):

* a prediction takes **4–7 ms**, the first one after startup about 34 ms (the pipeline warms up);
* the process needs about **220 MB** of memory with the model loaded;
* a new version behind the alias was in use **within one `MODEL_RELOAD_SECONDS` interval**.

In the container the same prediction first took **68 ms**. One row is far too
little work to share between threads, and all of that time went into starting
and synchronising the OpenMP threads scikit-learn uses. The image therefore
sets `OMP_NUM_THREADS=1`, which brings the prediction back to **3.3 ms**.

## Tests

```bash
uv run pytest
```

115 tests, under a second, no network. A real but very small scikit-learn pipeline is saved once in
MLflow's own format, and a fake source hands that folder to the service instead of downloading it.
Everything after the download is the real code: the checksum, the deserialization, the prediction.

The tests cover the settings, every kind of refused input, the rate limit, the readiness before and
after loading, the refusal to open a model with a wrong checksum, the swap to a new version while
the service runs, the metric names and labels, and the JSON log lines.
