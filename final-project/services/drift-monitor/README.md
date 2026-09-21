# drift-monitor

Batch job that answers one question: does the traffic the model sees still look like the data it
was trained on? It reads the prediction logs of the inference service back from Loki. It compares
them with the reference sample and pushes the result to the PushGateway. In the cluster it is a
Kubernetes CronJob.

```bash
uv sync
# against Loki, the way the CronJob runs it
LOKI_URL=http://localhost:3100 PUSHGATEWAY_URL=http://localhost:9091 \
  uv run python -m drift_monitor

# without any of that: compare a CSV file with the reference
uv run python -m drift_monitor --current-csv /tmp/live.csv
```

## What one run does

1. reads the reference sample `data/reference.csv` (2500 rows from the training split);
2. reads the live data: either the `prediction` log events of the last hour from Loki, or a CSV file
   given with `--current-csv`;
3. stops early when there are fewer than `MIN_SAMPLES` rows, pushes only the row count and the time,
   and exits 0;
4. runs the Evidently data drift report over the eight feature columns;
5. prints the result as one JSON log line and pushes the metrics.

Finding drift is **not** an error. The job exits 0 and Prometheus decides what to alert on. A
non-zero exit code means the check could not be made at all.

## Settings

Every setting is an environment variable and a command line option. The option wins.

| Variable | Option | Default | What it is |
|---|---|---|---|
| `LOKI_URL` | `--loki-url` | `http://loki-gateway.monitoring.svc.cluster.local` | the Loki gateway |
| `LOKI_QUERY` | `--loki-query` | see below | the LogQL query |
| `WINDOW_MINUTES` | `--window-minutes` | `60` | how far back to look |
| `LOKI_LIMIT` | `--limit` | `5000` | most lines to ask for |
| `MIN_SAMPLES` | `--min-samples` | `100` | fewer rows than this and no check is made |
| `PUSHGATEWAY_URL` | `--pushgateway-url` | empty, which means do not push | the PushGateway |
| `PUSH_JOB` | `--push-job` | `drift_monitor` | the `job` label of the pushed metrics |
| `REFERENCE_PATH` | `--reference-csv` | see below | the reference sample |
| `REPORT_DIR` | `--report-dir` | not set | save the Evidently HTML report here |
| | `--current-csv` | not set | read the live data from a file instead of Loki |
| `DO_NOT_TRACK` | | `1` | switches off the Evidently telemetry |

The default query is

```logql
{namespace="production", app="inference"} | json | event="prediction"
```

`REFERENCE_PATH` has two defaults, and the first one that exists is used. Inside the container it is
`/app/data/reference.csv`, because the image is built with `final-project/` as the build context. In
the repository it is `final-project/data/reference.csv`.

An empty `PUSHGATEWAY_URL` is on purpose: a local run then prints the numbers and touches nothing.

## Reading the logs back from Loki

The inference service prints one JSON object per prediction, with the eight features under
`features`. In a `query_range` answer every stream holds
`values: [[<nanosecond timestamp as a string>, <log line>], ...]`. The log line is still exactly the
JSON the service printed, because `| json` in the query only adds labels.

A log stream carries more than predictions, and a line can arrive cut in half. So lines that do not
parse, or that are not prediction events, are counted and skipped. They are never fatal. Rows
missing a feature are dropped as well. Both counts are in the `loaded_current` log line.

## The drift check

Evidently 0.7 with `DataDriftPreset(method="psi")` over the eight feature columns. **Current data
first, reference second.** PSI is a distance: a high score means drift, and the default threshold
per column is 0.1. The method is pinned because the default score of the preset is a p-value, where
a *low* value means drift. The two read in opposite directions, and a dashboard should never have
to guess which one it is showing.

The target column `MedHouseVal` is dropped. Live there is no target, only a prediction, and a
prediction is not a real house price. Comparing the two would report drift that is not there.

### What PSI does and does not see on this dataset

PSI puts the values into bins built from the reference. The reference of California Housing has very
long tails: `AveOccup` goes up to 1243 and `Population` up to 15507, while normal rows are far below
that. Measured on real runs:

| Change to the live data | PSI |
|---|---|
| `AveOccup` × 2 or × 5 | 0.0008 (not seen at all) |
| `AveOccup` × 20 | 0.11 |
| `Population` × 2 | 0.99 |
| `AveRooms` × 2 | 0.91 |
| `MedInc` × 2.5 | 3.08 |
| `HouseAge` replaced by uniform(1, 6) | 9.80 |

So a change in a long-tailed column has to be large before the score moves. This is worth knowing
before an alert threshold is chosen. The columns with a narrow range react quickly, the ones with
outliers do not. A reference sample with the tails clipped would react much faster. But the
reference has to stay the data the model was really trained on, so it is left as it is.

## Metrics

Pushed under the job `drift_monitor`, so every run replaces the previous values:

| Metric | What it is |
|---|---|
| `data_drift_share` | share of feature columns that drifted, 0 to 1 |
| `data_drift_columns` | how many columns drifted |
| `data_drift_score{column}` | the PSI distance of one column |
| `data_drift_samples` | rows of live data used |
| `data_drift_last_run_timestamp_seconds` | when the check ran |

With too few rows only the last two are pushed. A dashboard can then tell "no traffic" apart from
"the job stopped running", which a missing metric could not.

## Logs

One JSON object per line on stdout, the same shape as the inference service, so one LogQL query
covers both:

```json
{"ts": "2026-09-20T20:00:30.655Z", "level": "INFO", "event": "drift_checked",
 "service": "drift-monitor", "method": "psi", "samples": 800, "drifted_columns": 2,
 "drifted_share": 0.25, "threshold": 0.1, "drifted": ["HouseAge", "MedInc"],
 "scores": {"AveBedrms": 0.0068, "...": 0.0}}
```

Events: `started`, `loaded_reference`, `loaded_current`, `not_enough_samples`, `drift_checked`,
`report_saved`, `pushed_metrics`, `push_skipped`, `failed`. A failure prints the message in the log
line and the traceback on stderr. That way stdout stays one JSON object per line.

## Tests

```bash
uv run pytest
```

31 tests, about 3 seconds, and **no network**. The Loki answer is a fixture file
(`tests/fixtures/loki_query_range.json`) with two streams, a `request` event and a line cut in half.
The PushGateway call is replaced in every test. The drift tests use the real reference file: a
sample of it must show no drift, and the same sample with three features moved must show exactly
those three.
