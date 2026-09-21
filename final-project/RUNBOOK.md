# Runbook

What to do, step by step, when something has to change or something is broken.
Every section is **symptoms → checks → actions → how to confirm it is fixed**.

The Grafana alert rules link straight into this file, so the anchors below are
written out by hand and do not depend on the heading text.

Before anything else, point `kubectl` at the cluster:

```bash
aws eks update-kubeconfig --name mlops-final --region us-east-1 --profile goit
```

## Contents

| Task or incident | Section |
|---|---|
| Roll out a new model version | [Roll out a new model version](#roll-out-a-new-model-version) |
| Roll back | [Roll back](#roll-back) |
| Latency above the threshold | [Latency](#latency) |
| Error rate above 1 % | [Error rate](#error-rate) |
| Data drift detected | [Data drift](#data-drift) |
| The drift job is not running | [Drift job](#drift-job) |
| A canary aborted by itself | [A canary aborted by itself](#a-canary-aborted-by-itself) |
| A model fails the checksum | [A model fails the checksum](#a-model-fails-the-checksum) |
| MLflow answers 403 Invalid Host header | [MLflow answers 403](#mlflow-answers-403) |
| An Argo CD app is stuck or a namespace will not delete | [Argo CD app stuck](#argocd-app-stuck) |
| Rotate the generated passwords | [Rotate the generated passwords](#rotate-passwords) |
| Delete the whole infrastructure | [Delete the whole infrastructure](#teardown) |

## Getting at the user interfaces

Nothing is public. Each of these opens one port on the machine and holds it
until `Ctrl+C`.

```bash
kubectl -n argocd      port-forward svc/argocd-server 8080:80   # Argo CD
kubectl -n mlops-system port-forward svc/mlflow       5000:5000 # MLflow
kubectl -n monitoring  port-forward svc/grafana       3000:80   # Grafana
kubectl -n monitoring  port-forward svc/prometheus-server 9090:80
kubectl -n production  port-forward svc/inference     8000:80   # the API
```

Passwords:

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo
kubectl -n monitoring get secret grafana-admin \
  -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

> A port-forward binds to one **pod**, not to the Service. Restarting or
> replacing that pod kills the forward without a message. Start it again.

<a id="roll-out-a-new-model-version"></a>

## Roll out a new model version

This is the normal working path. Training and deploying are two separate
actions with two separate triggers.

### 1. Train

Run the workflow **final-project-train** in GitHub Actions (Actions →
final-project-train → Run workflow). All inputs are optional; leaving them
empty trains on the whole dataset with the image built from the current commit.

It starts the Step Functions state machine, waits for it, and writes the result
into the job summary: model name, version, `rmse`, `mae`, `r2`, `run_id`,
`dataset_sha256` and `model_sha256`. Write down the **version** and the
**`model_sha256`** — the promotion needs both.

By hand instead:

```bash
aws stepfunctions start-execution \
  --state-machine-arn "$(terraform -chdir=terraform/stacks/platform output -raw state_machine_arn)" \
  --region us-east-1 --profile goit \
  --input '{"image_tag":"<commit sha>","git_sha":"<commit sha>","params":{}}'
```

### 2. Check it in staging

The training job gives every new version the alias `staging`. The staging pods
check that alias every 60 seconds and swap the model in without a restart, so
nothing has to be deployed.

```bash
kubectl -n staging port-forward svc/inference 8000:80 &
curl -s localhost:8000/info | jq
```

`model_version` should be the new number within a minute. Send it some traffic
and look at the answers:

```bash
python3 scripts/send_traffic.py --mode normal --count 200 --rate 10 \
  --url http://localhost:8000
```

### 3. Promote: one commit

Edit `gitops/envs/production.yaml` and change exactly two lines:

```yaml
modelVersion: "4"
modelSha256: "<the 64 hex characters from the training summary>"
```

```bash
git commit -am "Promote model version 4 to production"
git push
```

Nothing else. Argo CD sees the commit within a minute.

### 4. Watch the canary

```bash
kubectl argo rollouts get rollout inference -n production --watch
```

Expected: 1 new pod out of 10 → a two minute pause → 5 out of 10 → a two minute
pause → all 10. The background analysis queries Prometheus every 30 seconds for
the 5xx share of the new version and aborts after three failed measurements in
a row.

Without the plugin:

```bash
kubectl -n production get rollout inference -o wide
kubectl -n production get pods -L model-version
```

### 5. Confirm

```bash
# the pods serve the new version
kubectl -n production port-forward svc/inference 8000:80 &
curl -s localhost:8000/info | jq '.model_version, .model_sha256'

# the registry agrees: the PostSync hook ran after the canary finished
kubectl -n production logs job/inference-registry-sync
```

The hook prints one JSON audit line. In Grafana → Explore → Loki:

```logql
{app="registry-ops"} | json | event="model_registry_audit"
```

It names the action, the new version, the version that was archived, the actor
(`argocd`) and the commit.

<a id="roll-back"></a>

## Roll back

**Symptoms.** The new version is worse: wrong predictions, higher latency,
errors that the canary did not catch, or a business decision.

**Action — one command:**

```bash
git revert <the promotion commit>
git push
```

That puts the old `modelVersion` and `modelSha256` back. Argo CD syncs, Argo
Rollouts runs the canary again in the other direction, and after it finishes
the `PostSync` hook runs `registry_ops sync --production-version <old>`, which
moves the `production` alias and the `Production` stage back and archives the
version that was live.

**Checks.**

```bash
kubectl argo rollouts get rollout inference -n production --watch
curl -s localhost:8000/info | jq '.model_version'
```

**If the registry has to be fixed without a deployment** — the escape hatch,
for example when the Job failed but the pods are fine:

```bash
kubectl -n mlops-system run registry-ops --rm -it --restart=Never \
  --image=<account-id>.dkr.ecr.us-east-1.amazonaws.com/final-project/registry-ops:<tag> \
  --env MLFLOW_TRACKING_URI=http://mlflow.mlops-system.svc.cluster.local:5000 \
  --env ACTOR=manual-runbook \
  -- python -m registry_ops rollback
```

`rollback` goes to the alias `previous-production`; `rollback --version N` goes
to a named version. It prints the same audit line. Remember that Git is still
the source of truth: if the values file was not changed, the next sync of the
hook will move the registry back.

**Aborting a canary by hand**, when it is going wrong but has not failed enough
measurements yet:

```bash
kubectl argo rollouts abort inference -n production
```

The old pods take all the traffic again straight away. The Application goes
`Degraded`, so the `PostSync` hook does **not** run and the registry keeps
naming the old version — which is correct. Afterwards, `git revert` the
promotion commit, otherwise Argo CD's self-heal will start the canary again.

<a id="inference-latency"></a>
<a id="latency"></a>

## Latency

**Alert:** *Inference p95 latency is too high* — p95 over 250 ms in
`production` for 5 minutes. The service answers in about 5 ms when it is
healthy.

**Checks.**

In Prometheus (`localhost:9090`) or Grafana → Explore:

```promql
# p95 per model version: is it one version or all of them?
histogram_quantile(0.95, sum by (le, model_version) (
  rate(inference_request_duration_seconds_bucket{namespace="production"}[5m])))

# is a pod short of CPU?
sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="production"}[5m]))

# how much traffic is there at all?
sum(rate(inference_requests_total{namespace="production"}[5m]))
```

```bash
kubectl -n production get pods -L model-version
kubectl top pods -n production
kubectl top nodes
kubectl -n production get events --sort-by=.lastTimestamp | tail -20
```

**Actions.**

| What the checks show | Do this |
|---|---|
| Only the new `model_version` is slow, a canary is running | `kubectl argo rollouts abort inference -n production`, then `git revert` the promotion commit. Section [Roll back](#roll-back). |
| Every pod is slow, nodes are near 100 % CPU | The cluster is too small. Raise `node_desired_size` in `terraform/stacks/infra/variables.tf` and apply, or lower `replicas` in `gitops/envs/production.yaml`. This costs money: ask the platform lead. |
| A few pods are slow, the node is fine | Look for a pod that never became ready: `kubectl -n production describe pod <name>`. A pod that is restarting takes traffic in and out of the Service. |
| Latency is high and traffic is almost zero | Probably noise. The metric has few samples, so one slow request moves p95. Check the raw rate before acting. |

**Confirm.** p95 back under 250 ms for 10 minutes; the alert goes to `Normal`
in Grafana → Alerting → Alert rules.

<a id="inference-errors"></a>
<a id="error-rate"></a>

## Error rate

**Alert:** *Inference is returning server errors* — more than 1 % of
`production` requests end in 5xx for 5 minutes. Refused input (400) and rate
limiting (429) are counted separately and never trigger this rule, so a 5xx
means the service itself failed.

**Checks.**

```promql
# which version is failing
sum by (model_version) (rate(inference_requests_total{
  namespace="production", status_class="5xx"}[5m]))

# how big the share is
sum(rate(inference_requests_total{namespace="production", status_class="5xx"}[5m]))
/ clamp_min(sum(rate(inference_requests_total{namespace="production"}[5m])), 0.001)

# has a model failed to load anywhere
sum by (reason) (inference_model_load_failures_total)
```

The reason is in the logs. Grafana → Explore → Loki:

```logql
{namespace="production", app="inference"} | json | level="error"
```

```bash
kubectl -n production get rollout inference
kubectl -n production get pods -L model-version
```

**Actions.**

1. **A canary is running and only the new version fails.** That is what the
   analysis is for; if it has not aborted yet, abort it by hand and revert the
   promotion commit. Section [Roll back](#roll-back).
2. **`event=fault_injected` in the logs.** Someone left `faultRate` at a
   non-zero value in `gitops/envs/production.yaml`. Set it back to `0` and
   commit.
3. **`event=checksum_mismatch`.** Section
   [A model fails the checksum](#a-model-fails-the-checksum).
4. **`event=internal_error`** with a traceback. The traceback names the line.
   If it comes from the model itself, roll back and hand it to the ML model
   owner.
5. **No pod is ready at all.** MLflow is probably down, so no pod can load a
   model: `kubectl -n mlops-system get pods`. Look at Postgres first, MLflow
   will not start without it.

**Confirm.** The 5xx rate is back at zero for 10 minutes, every pod is ready
(`kubectl -n production get pods`), and `/info` shows the version that is meant
to be live.

<a id="data-drift"></a>

## Data drift

**Alert:** *The live data no longer looks like the training data* — the drifted
share is above 0.25 for 5 minutes. That means at least two of the eight
features have moved a long way from the reference sample.

**Read the dashboard first.** Grafana → MLOps → *Model quality*:

- `data_drift_share` — how many of the eight features drifted, as a share.
- `data_drift_score{column}` — the PSI score per column. This is the panel that
  says *which* feature moved.
- `data_drift_samples` — how many prediction log lines the run had. Below the
  `minSamples` of 400 the job pushes only this number and exits, so a low value
  means "no verdict", not "no drift".
- `data_drift_last_run_timestamp_seconds` — when the last run finished.

Same numbers from Prometheus:

```promql
max(data_drift_share)
topk(3, data_drift_score)
max(data_drift_samples)
```

**Confirm it with a run you watch yourself.** Start one job by hand and read
its output; the CronJob does not keep the HTML report, but the log holds the
same numbers Evidently produced:

```bash
kubectl -n mlops-system create job drift-now --from=cronjob/drift-monitor
kubectl -n mlops-system logs job/drift-now -f
```

The log is JSON, one object per line, with the share, the column scores and the
number of samples.

**Two things to know about this dataset before deciding.**

- **The `AveOccup` blind spot.** PSI bins the live values into bins built from
  the reference, and `AveOccup` has a very long tail (up to 1243 in the
  reference). Measured: doubling or even quintupling `AveOccup` gives a PSI of
  0.0008 — invisible. It takes a factor of 20 to reach 0.11. Narrow columns
  such as `MedInc` or `HouseAge` react immediately. So **a low score on
  `AveOccup` is not proof that nothing changed.**
- **The 400 sample minimum.** Below 400 rows in the window, PSI on this data
  reports drift that is not there, purely because some bins end up empty by
  chance. The job refuses to judge below that number on purpose.

**Actions — the decision belongs to the ML model owner.**

| What is seen | Do this |
|---|---|
| Several narrow columns drifted and the samples are well over 400 | Real drift. Retrain: run the train workflow, check the metrics of the new version in staging, then promote. Section [Roll out a new model version](#roll-out-a-new-model-version). |
| One column drifted a lot, the others did not | Look upstream first. A single feature moving usually means the producer of that field changed, not that the world changed. |
| Samples just above 400 and the score is near the threshold | Wait for the next run. Two runs in a row above the threshold is the signal, one is not. |
| Drift is expected — a known seasonal change, or a deliberate change of input | Accept it, write down why in the pull request or the commit that changes the threshold, and either raise the threshold or refresh the reference sample with `scripts/make_reference.py`. |

**Confirm.** After a retrain and a promotion, the next drift run compares the
live traffic with the reference of the **new** training split, and
`data_drift_share` falls back under the threshold.

<a id="drift-job"></a>

## Drift job

**Alert:** *The drift job has not run for two hours.* The CronJob runs every 15
minutes, so two hours of silence means it is failing, cannot reach Loki or the
PushGateway, or is not scheduled at all.

**Checks.**

```bash
kubectl -n mlops-system get cronjob drift-monitor
kubectl -n mlops-system get jobs -l app.kubernetes.io/name=drift-monitor
kubectl -n mlops-system logs -l app.kubernetes.io/name=drift-monitor --tail=50
kubectl -n mlops-system describe cronjob drift-monitor | tail -20
```

```promql
time() - max(data_drift_last_run_timestamp_seconds)
```

**Actions.**

| Symptom | Cause | Do this |
|---|---|---|
| `SUSPEND: True` | somebody suspended it | `kubectl -n mlops-system patch cronjob drift-monitor -p '{"spec":{"suspend":false}}'` — and note that Argo CD self-heal would have done it anyway within a minute. |
| Jobs exist but all fail | Loki or the PushGateway is unreachable | `kubectl -n monitoring get pods`. Test from inside: `kubectl -n mlops-system run curl --rm -it --image=curlimages/curl --restart=Never -- curl -s http://loki.monitoring.svc.cluster.local:3100/ready` |
| `not_enough_samples` in every log | nobody is calling `/predict` | Expected on an idle cluster. Send traffic: `python3 scripts/send_traffic.py --mode normal --count 500 --rate 15 --url http://localhost:8000` against a port-forward to `production`. |
| No Jobs at all | the CronJob was missed while the cluster was busy | `startingDeadlineSeconds` is 300, so a very late run is skipped rather than queued. Run one by hand: `kubectl -n mlops-system create job drift-now --from=cronjob/drift-monitor` |
| The pod is `Pending` | no room on the nodes | `kubectl -n mlops-system describe pod <name>`, look at Events. Section [Latency](#latency) covers the capacity case. |

**Confirm.**

```bash
kubectl -n mlops-system create job drift-now --from=cronjob/drift-monitor
kubectl -n mlops-system logs job/drift-now -f
```

`data_drift_last_run_timestamp_seconds` moves and the alert returns to
`Normal`. Delete the manual job afterwards: `kubectl -n mlops-system delete job
drift-now`.

<a id="a-canary-aborted-by-itself"></a>

## A canary aborted by itself

**Symptoms.** The Argo CD Application `inference-production` is `Degraded`. The
Rollout says `Degraded` with `RolloutAborted`. Production is serving the **old**
version — which is the point.

**Checks.**

```bash
kubectl argo rollouts get rollout inference -n production
kubectl -n production describe rollout inference | tail -30

# which analysis run failed, and on what
kubectl -n production get analysisruns
kubectl -n production describe analysisrun <name>
```

The `Message` of the failed measurement holds the value the query returned. Two
different things can have happened:

1. **The analysis failed three times in a row.** The new version really did
   return more than `analysisErrorRateMax` (5 %) of 5xx. Look at the error
   logs of the new version in Loki and treat it as section
   [Error rate](#error-rate).
2. **The progress deadline ran out.** `progressDeadlineSeconds` is 600 and
   `progressDeadlineAbort: true`. This is what happens when the new pods never
   become ready — almost always a checksum mismatch, see
   [A model fails the checksum](#a-model-fails-the-checksum).

**Actions.**

Production is safe, so there is no hurry. Undo the promotion so Argo CD stops
trying:

```bash
git revert <the promotion commit>
git push
```

Without the revert, self-heal will start the same canary again on the next
reconciliation.

**Confirm.** The Application is `Synced/Healthy` again, the Rollout is
`Healthy`, `curl /info` shows the old version, and the registry still names the
old version as production — the `PostSync` hook never ran.

<a id="a-model-fails-the-checksum"></a>

## A model fails the checksum

**Symptoms.** Pods start but never become ready; `/health/ready` answers 503.
`kubectl get pods` shows `0/1 Running`. The log has
`event=checksum_mismatch` and
`inference_model_load_failures_total{reason="checksum_mismatch"}` is above
zero.

This is the safety net working. The service hashes the model file **before**
unpickling it and refuses to load a file that does not match.

**Checks.**

```bash
kubectl -n production logs <pod> | grep checksum_mismatch
```

The line holds `expected` and `got`. Compare with the two places the value
comes from:

- the model version tag `model_sha256` in MLflow (UI, or `python -m registry_ops list`),
- `modelSha256` in `gitops/envs/production.yaml`.

**Actions.**

| Which two values disagree | Cause | Do this |
|---|---|---|
| Git ≠ registry tag, and the registry tag matches the file | A typo in the promotion commit. | Fix `modelSha256` in `gitops/envs/production.yaml` and commit. |
| Registry tag ≠ the file that was downloaded | The artifact in S3 changed after training. | **Treat this as a security incident.** Do not load the version. Look at the object versions in the artifact bucket (`aws s3api list-object-versions`), check CloudTrail for who wrote it, and promote a known good version instead. |
| Both match but the pod still fails | A truncated download. | `kubectl -n production delete pod <name>` and watch it retry. If it happens again, look at MLflow: a proxied artifact download that returns a short file used to be a real bug in an older setup. |

**Confirm.** The pod reaches `1/1 Running`, `/health/ready` returns 200, and
`curl /info` shows the version and its `model_sha256`.

<a id="mlflow-answers-403"></a>

## MLflow answers 403

**Symptoms.** MLflow returns `403` with `Invalid Host header` — from the
browser through a port-forward, or from the training job.

**Cause.** MLflow 3 checks the `Host` header of every request against
`serverAllowedHosts` in `gitops/apps/mlflow/values.yaml`. The port is part of
that header. `/health` and `/version` are never checked, which is why the
probes stay green while everything else is refused.

**Checks.**

```bash
kubectl -n mlops-system get deploy mlflow -o yaml | grep -A5 allowed-hosts
curl -s -o /dev/null -w '%{http_code}\n' localhost:5000/health   # 200
curl -s -o /dev/null -w '%{http_code}\n' localhost:5000/         # 403 if this is it
```

**Actions.**

- Using a port that is not in the list (the list covers `localhost:*` and
  `127.0.0.1:*`): use `localhost` and not the machine's own hostname or IP.
- A client inside the cluster that uses a name which is not listed: add it to
  `serverAllowedHosts` and commit. The file already covers every short form of
  `mlflow.mlops-system.svc.cluster.local` plus `10.*`.

**Confirm.** `curl -s localhost:5000/api/2.0/mlflow/experiments/search -X POST
-H 'Content-Type: application/json' -d '{"max_results":1}'` returns JSON, and
the UI opens.

<a id="argocd-app-stuck"></a>

## Argo CD app stuck

**Symptoms.** An Application stays `OutOfSync`, or `Progressing` forever, or a
namespace hangs in `Terminating` during a teardown.

**Checks.**

```bash
kubectl -n argocd get applications
kubectl -n argocd describe application <name> | tail -40
kubectl -n argocd logs deploy/argocd-repo-server --tail=100
kubectl -n argocd logs statefulset/argocd-application-controller --tail=100
```

**Actions.**

| Symptom | Do this |
|---|---|
| `ComparisonError` about rendering | Reproduce it locally: `scripts/validate_gitops.sh`. It renders every chart with the same values Argo CD uses. |
| Stuck on a CustomResourceDefinition that is "too long" | The `argo-rollouts` Application syncs with `ServerSideApply=true` for exactly this reason. If a new chart hits it, add the same sync option in `gitops/bootstrap/templates/`. |
| Healthy children, `Progressing` parent | The parent waits for the children because of the `Application` health customisation in `terraform/modules/argocd/values/argocd-values.yaml`. Look for the child that is not healthy yet. |
| The whole namespace hangs in `Terminating` | **The finalizer deadlock.** Argo CD puts `resources-finalizer.argocd.argoproj.io` on every Application it creates. If the controller is gone, nothing processes those finalizers. |

Clearing the finalizer deadlock:

```bash
kubectl -n argocd get applications -o name | while read -r app; do
  kubectl -n argocd patch "$app" --type=merge \
    -p '{"metadata":{"finalizers":[]}}'
done
```

If `terraform destroy` already failed with `Failed to purge the release:
release: not found`, the Helm release really was uninstalled; drop it from the
state and run destroy again:

```bash
terraform -chdir=terraform/stacks/platform state rm 'module.argocd.helm_release.argocd'
terraform -chdir=terraform/stacks/platform destroy
```

**The way to avoid all of this** is the teardown order below: delete the root
Application first, wait, and only then let Terraform remove Argo CD.

<a id="rotate-passwords"></a>

## Rotate the generated passwords

Two passwords are generated by Terraform: the MLflow Postgres password
(`mlflow-postgres` in `mlops-system`) and the Grafana admin password
(`grafana-admin` in `monitoring`). Neither is in Git; both are `random_password`
resources in the platform stack.

**The Grafana password** can be rotated on its own:

```bash
cd terraform/stacks/platform
terraform apply -replace='module.monitoring.random_password.grafana_admin'
kubectl -n monitoring rollout restart deployment grafana
```

Grafana reads the secret at start, so it has to restart.

**The Postgres password** is harder, because rotating it changes only what
Kubernetes holds, not what the running database accepts. The honest path for a
project of this size is to accept a short outage:

```bash
# 1. new password in the secret
cd terraform/stacks/platform
terraform apply -replace='module.mlflow.random_password.postgres'

# 2. change it in the database as well
kubectl -n mlops-system exec -it statefulset/postgres -- \
  psql -U mlflow -c "ALTER USER mlflow WITH PASSWORD '<the new value>';"

# 3. restart the client
kubectl -n mlops-system rollout restart deployment mlflow
```

Read the new value with:

```bash
kubectl -n mlops-system get secret mlflow-postgres \
  -o jsonpath='{.data.password}' | base64 -d; echo
```

The Argo CD admin password is created by the chart, not by Terraform. Rotate it
by deleting `argocd-initial-admin-secret` and restarting `argocd-server`, or
better, set a new one in the Argo CD UI under User Info.

**Confirm.** MLflow's pod is `1/1 Running` and its log has no authentication
error; Grafana accepts the new password.

<a id="teardown"></a>

## Delete the whole infrastructure

**Do this at the end of every working session.** The cluster costs about
$0.28 per hour, roughly $6.70 a day, and there is no free tier on this account.

**The order matters.** Argo CD created the volumes, not Terraform, so Terraform
cannot delete them. And if Argo CD is removed first, nothing is left to process
the finalizers on its Applications.

```bash
# 1. Delete the root Application. The finalizer makes this delete every child
#    Application, every workload and every PVC, which releases the EBS volumes.
kubectl -n argocd delete application mlops-platform

# 2. Wait until no volume is left. This usually takes two or three minutes.
kubectl get pvc -A
kubectl get pv

# 3. The platform stack: Argo CD, the secrets, MLflow's bucket, the training
#    pipeline, the namespaces.
cd terraform/stacks/platform
terraform destroy

# 4. The infra stack, last: it deletes the cluster the platform stack used.
cd ../infra
terraform destroy
```

**Then check that nothing is left**, because a resource created from inside the
cluster is not in any Terraform state:

```bash
export AWS_PROFILE=goit
aws eks list-clusters --region us-east-1
aws ec2 describe-instances --region us-east-1 \
  --filters Name=instance-state-name,Values=running --query 'Reservations[].Instances[].InstanceId'
aws ec2 describe-volumes --region us-east-1 --query 'Volumes[].VolumeId'
aws ec2 describe-nat-gateways --region us-east-1 \
  --filter Name=state,Values=available --query 'NatGateways[].NatGatewayId'
aws ec2 describe-addresses --region us-east-1 --query 'Addresses[].AllocationId'
aws elbv2 describe-load-balancers --region us-east-1 --query 'LoadBalancers[].LoadBalancerArn'
```

All of these should come back empty.

**What is kept on purpose:** the Terraform state bucket
`mlops-tfstate-goit-447ede`. It is not managed by Terraform, so no destroy can
delete the state it holds. It costs a few cents a month. See
[`scripts/create_state_bucket.sh`](scripts/create_state_bucket.sh).

**If step 3 or 4 fails**, the cause is almost always the finalizer deadlock:
see [Argo CD app stuck](#argocd-app-stuck).
