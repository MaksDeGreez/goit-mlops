# drift-monitor chart

One `CronJob` in namespace `mlops-system`, plus the `ServiceAccount` it runs as. Every 15 minutes it
reads the `prediction` log lines of the production pods back out of Loki, compares the eight
features with the reference sample from the training split, and pushes the result to the
PushGateway. Grafana reads it from Prometheus and alerts on it.

The job itself is documented in [`../../../services/drift-monitor/README.md`](../../../services/drift-monitor/README.md),
including what PSI does and does not see on this dataset.

## Values

| Key | Default | What it is |
|---|---|---|
| `imageRegistry` | — | ECR registry host. The Application injects it; rendering fails without it |
| `lokiUrl` | `http://loki.monitoring.svc.cluster.local:3100` | where the log lines come from |
| `pushgatewayUrl` | `http://pushgateway.monitoring.svc.cluster.local:9091` | where the metrics go |
| `imageTag` | short git sha | image tag, written by the CI pipeline |
| `schedule` | `*/15 * * * *` | |
| `lokiQuery` | `{namespace="production", app="inference"} \| json \| event="prediction"` | |
| `windowMinutes` | `60` | how far back each run looks |
| `lokiLimit` | `5000` | most log lines asked for |
| `minSamples` | `400` | below this the job pushes only the row count and exits 0 |
| `pushJob` | `drift_monitor` | the `job` label of the pushed metrics |
| `referencePath` | `""` | empty means `/app/data/reference.csv` inside the image |
| `cpuRequest` | `200m` | |
| `memoryRequest` | `320Mi` | a measured run used 287 MiB |
| `cpuLimit` | `""` | empty means no CPU limit |
| `memoryLimit` | `640Mi` | |
| `backoffLimit` | `1` | |
| `activeDeadlineSeconds` | `600` | |
| `startingDeadlineSeconds` | `300` | |
| `successfulJobsHistoryLimit` | `3` | |
| `failedJobsHistoryLimit` | `3` | |

## Two numbers that were measured, not guessed

**Memory: 287 MiB.** One run over the 2500 row reference sample on the development machine, measured
with `/usr/bin/time -l`. Almost all of it is importing pandas and Evidently, so the number barely
moves with the number of rows. The request is 320Mi and the limit 640Mi, which leaves room for a
full 5000 row window. The run took under 3 seconds.

**`minSamples: 400`.** PSI puts the live values into bins built from the reference. With a small
sample some bins end up empty by chance alone and the score jumps, which looks exactly like drift.
400 rows is where that stops on this dataset. Below it the job pushes only `data_drift_samples` and
the timestamp and exits 0, so a dashboard can tell "no traffic" apart from "the job stopped
running".

## Why the runs overlap

The schedule is every 15 minutes and the window is 60 minutes, so each run looks at data three
earlier runs have already seen. That is on purpose: a short burst of odd traffic is then measured
four times instead of being missed because it fell between two windows. `concurrencyPolicy: Forbid`
still makes sure two runs never exist at the same time, because both would push the same metric
under the same `job` label.

## Checking the chart without a cluster

```bash
cd final-project/gitops
REG=111122223333.dkr.ecr.us-east-1.amazonaws.com   # any value, it is only a string here

helm lint charts/drift-monitor --set imageRegistry=$REG
helm template drift-monitor charts/drift-monitor -n mlops-system --set imageRegistry=$REG \
  | kubeconform -strict -summary -kubernetes-version 1.35.0 -schema-location default -
```
