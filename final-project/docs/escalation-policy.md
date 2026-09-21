# Escalation policy

Which alert goes where, who answers it and how long they have.

## A note on the contact point, up front

Grafana sends the alerts itself; there is no Alertmanager. There is exactly one
contact point, `platform-team`, and it is an **email address that does not
exist**: `mlops-alerts@example.com`, in
`gitops/apps/grafana/values.yaml`. No SMTP server is configured in
`grafana.ini` either, so **nothing is really sent**. The rules, the severities,
the grouping and the routing are all real and provisioned from Git; only the
last step is a placeholder.

In a real project that address would be a team mailbox or a Slack webhook, and
the `severity: critical` route would additionally go to a paging service. The
change is two lines in the values file.

Until then, alerts are seen in Grafana under **Alerting → Alert rules**
(`kubectl -n monitoring port-forward svc/grafana 3000:80`).

## Roles

Nobody is named. One person happens to fill all three roles in this project,
but the responsibilities are different and the runbook is written for the
roles.

| Role | Responsible for |
|---|---|
| **On-call MLOps engineer** | First response to every alert. Owns the platform: cluster, Argo CD, monitoring, the inference service. |
| **ML model owner** | Owns the model and the data. Decides whether to retrain, to accept drift or to roll back for quality reasons. |
| **Platform lead** | Decides on anything that costs money, changes the architecture, or has to be communicated outside the team. |

## The alerts

All four rules are provisioned in `gitops/apps/grafana/values.yaml` and every
one of them carries a `runbook_url` that links to the matching section of
[`../RUNBOOK.md`](../RUNBOOK.md).

| Alert | Severity | Fires when | Notified first | First response | Runbook |
|---|---|---|---|---|---|
| Inference p95 latency is too high | `warning` | p95 over 250 ms in `production` for 5 min | on-call MLOps engineer | 30 minutes, working hours | [`#inference-latency`](../RUNBOOK.md#inference-latency) |
| Inference is returning server errors | `critical` | over 1 % of 5xx in `production` for 5 min | on-call MLOps engineer | 15 minutes, any time | [`#inference-errors`](../RUNBOOK.md#inference-errors) |
| The live data no longer looks like the training data | `warning` | drifted share over 0.25 for 5 min | on-call MLOps engineer, then the ML model owner | 1 working day | [`#data-drift`](../RUNBOOK.md#data-drift) |
| The drift job has not run for two hours | `warning` | no drift result for 2 hours | on-call MLOps engineer | 1 working day | [`#drift-job`](../RUNBOOK.md#drift-job) |

Grafana's notification policy groups by `alertname` and `namespace`. Critical
alerts wait 30 seconds before the first message and repeat every hour; warnings
wait 5 minutes and repeat every 12 hours. That is also in the values file.

## What the on-call person actually sees

One of the four rules has fired for real, which is the best way to describe the
experience. After 6000 drifted requests, *The live data no longer looks like
the training data* went from `Normal` to `Firing`
([demo trace](demo-trace.md#9-drift-and-the-alert-that-fired)).

Under **Alerting → Alert rules** the rule turns red with `1 instance`. Opening
it shows, on one page: the query `max(data_drift_share)`, the graph of that
value over the last three hours, the reduced number (0.375) next to the
threshold (0.25), the pending period (5 minutes), the labels
`severity=warning` and `team=mlops`, and the **Runbook URL** link. That link is
the first click: it opens [`../RUNBOOK.md#data-drift`](../RUNBOOK.md#data-drift),
which says which panel to read next and what each reading means.

So even with no contact point that delivers anything, the path from "something
is wrong" to "here is what to do" is two clicks. When the drifted traffic
stopped, the rule went back to `Normal` on its own.

## Who escalates to whom, and when

**Inference errors (critical).**
The on-call engineer starts within 15 minutes. If a canary is running, the
rollout is the first suspect and the runbook says how to abort it; that is a
platform action and needs nobody else. If the errors are there without a
rollout and the service does not recover within 30 minutes, the on-call
engineer calls the **platform lead**. If the errors turn out to come from the
model itself — for example predictions that are out of range — the **ML model
owner** is brought in and a rollback to the previous production version is the
default action.

**Latency (warning).**
Handled by the on-call engineer during working hours. Escalate to the platform
lead if the cause is capacity: more or bigger nodes cost money, and that is not
the on-call engineer's decision.

**Data drift (warning).**
The on-call engineer confirms that the drift is real (enough samples, not a
broken job) and hands it to the **ML model owner** the same working day. The
model owner decides between retraining, investigating the upstream data, or
accepting the drift and writing down why. The on-call engineer never retrains
a production model on their own.

**Drift job stale (warning).**
Purely a platform problem. The on-call engineer fixes the CronJob. No
escalation unless it turns out to be a cluster-wide failure, in which case the
critical path is whatever else is broken.

## Things that are deliberately not alerts

- **An aborted canary.** Argo Rollouts already stopped the bad version by
  itself, and the old version is serving. It shows up as a `Degraded`
  Application in Argo CD and is picked up in normal working hours. Paging
  somebody because the safety net worked is how people learn to ignore pages.
  Worth knowing: a canary bad enough to be aborted can still push the error
  rate over 1 % for a minute or two and set off the critical rule — measured
  2.08 % during the demo abort. The runbook's first question under
  [error rate](../RUNBOOK.md#inference-errors) is therefore "is a canary
  running", and the answer "yes, and it already aborted itself" closes the
  incident.
- **A failed training run.** The GitHub Actions job fails and shows the reason
  in its summary. Nobody is waiting on it at 3 a.m.
- **A single pod restart.** Kubernetes handles it. Repeated restarts show up as
  errors or latency, which are alerts.
