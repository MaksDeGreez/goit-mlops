# inference chart

Deploys the prediction API into one namespace. Two ArgoCD Applications use it:
`inference-staging` (namespace `staging`) and `inference-production` (namespace `production`). The
values of each one are in [`../../envs`](../../envs).

What it creates:

| Object | When | What it is for |
|---|---|---|
| `Rollout` `inference` | always | the pods, with a canary strategy instead of a rolling update |
| `Service` `inference` | always | one ClusterIP in front of old and new pods |
| `ServiceAccount` `inference` | always | so the pods do not use the shared `default` account |
| `AnalysisTemplate` `inference-error-rate` | canary + analysis + a pinned version | the rule that aborts a bad canary |
| `PodDisruptionBudget` `inference` | `pdbEnabled` | keeps most pods alive while a node is drained |
| `Job` `inference-registry-sync` | `registrySyncEnabled` and a pinned version | PostSync hook, moves the MLflow alias and stage |

## Why canary

The service answers one small HTTP request, and a bad model version shows up in the error rate
within a minute. A canary can therefore try the new version on a tenth of the traffic, look at the
error rate, and go back on its own. Blue-green would need a second full copy of ten pods on a two
node cluster, and A/B testing would need a traffic router to split by header. Neither buys anything
here.

There is no traffic router in this cluster, so the split is done with replicas: one Service sends
requests to every ready pod, and the new version gets the share of the pods it has. With ten pods
the first step is one pod, which is the 10 % the assignment asks for.

## Values

Flat keys, because these files are edited by hand and a deep values file is hard to read.

| Key | Default | What it is |
|---|---|---|
| `imageRegistry` | — | ECR registry host. The Application injects it; rendering fails without it |
| `mlflowTrackingUri` | `http://mlflow.mlops-system.svc.cluster.local:5000` | where the model comes from |
| `prometheusAddress` | `http://prometheus-server.monitoring.svc.cluster.local` | where the analysis asks |
| `gitSha` | `unknown` | the commit ArgoCD is syncing, written into the audit line |
| `imageTag` | `latest` | image tag of the service |
| `modelName` | `california-housing` | name in the model registry |
| `modelVersion` | `""` | pinned version. Production sets it, staging leaves it empty |
| `modelAlias` | `staging` | alias to follow when no version is pinned |
| `modelSha256` | `""` | extra checksum the model file must match |
| `modelReloadSeconds` | `60` | how often the alias is checked |
| `replicas` | `2` | pods |
| `rateLimit` | `20/second` | limit of `/predict`, per client address |
| `faultRate` | `0` | share of `/predict` calls that fail on purpose. Demo only |
| `logLevel` | `INFO` | |
| `cpuRequest` | `100m` | |
| `memoryRequest` | `256Mi` | one pod uses about 220 MB with the model loaded |
| `cpuLimit` | `""` | empty means no CPU limit |
| `memoryLimit` | `384Mi` | |
| `canaryEnabled` | `false` | with `false` the Rollout does a plain rolling update |
| `canaryWeights` | `[10, 50]` | share of the pods the new version gets at each step |
| `canaryPauseSeconds` | `120` | how long each step waits |
| `revisionHistoryLimit` | `3` | old ReplicaSets kept |
| `progressDeadlineSeconds` | `600` | no progress for this long and the rollout aborts itself |
| `analysisEnabled` | `false` | background analysis during the canary |
| `analysisErrorRateMax` | `0.05` | more 5xx than this from the new version and the canary is aborted |
| `analysisIntervalSeconds` | `30` | time between measurements |
| `analysisInitialDelaySeconds` | `30` | wait before the first one |
| `analysisFailureLimit` | `2` | failed measurements tolerated; the next one aborts |
| `registrySyncEnabled` | `false` | the PostSync hook. Production only |
| `registryOpsImageTag` | `latest` | image tag of the hook |
| `pdbEnabled` | `false` | |
| `pdbMinAvailable` | `8` | |

## A promotion is one line

```diff
 # final-project/gitops/envs/production.yaml
-modelVersion: "3"
-modelSha256: "1b7f...  "
+modelVersion: "4"
+modelSha256: "9f2c...  "
```

```bash
git commit -am "Promote model version 4 to production"
git push
```

ArgoCD sees the commit and syncs. Because both the environment variable and the pod label change,
the Rollout starts a new revision and runs the canary: 1 pod, wait, 5 pods, wait, all 10. When it is
done the PostSync hook runs `registry_ops sync --production-version 4`, which sets the MLflow alias
`production` and the stage `Production` on version 4 and archives version 3.

## A rollback is one command

```bash
git revert <the promotion commit>
git push
```

The file is back to the older version, and everything else follows: the same canary in the other
direction and a hook that moves the registry back. The old version is still there, still tagged, and
`previous-production` points at the one that just left.

## The automatic rollback, and how to show it

The analysis asks Prometheus one question every 30 seconds:

```promql
(sum(rate(inference_requests_total{namespace="production", model_version="4", status_class="5xx"}[2m])) or vector(0))
/
 sum(rate(inference_requests_total{namespace="production", model_version="4"}[2m]))
```

Only the new version is measured, because every metric of the service carries `model_version`. 4xx
is left out: a refused input or a rate limited client is not a broken release.

The measurement counts as good when the share is at most `analysisErrorRateMax`, **and also** when
there is no data at all (`len(result) == 0`) or the version served nothing in the window
(`isNaN(result[0])`). Missing data is not evidence of a bad version, and a rollout that nobody sends
traffic to must not be rolled back for being quiet. `analysisFailureLimit: 2` means the third bad
measurement in a row aborts the canary; one odd scrape is not enough.

To show it without training a broken model, set the fault switch together with a new version:

```yaml
modelVersion: "5"
faultRate: 1
```

The one canary pod then answers every `/predict` with 500, the error rate of version 5 is 1.0, and
after three failed measurements Argo Rollouts scales the canary back to zero by itself. The
Application turns `Degraded`, the PostSync hook never runs, and MLflow still says version 4 is the
production one — which is true, because version 4 is what the pods went back to.

```bash
kubectl argo rollouts get rollout inference -n production --watch
kubectl -n production get analysisruns
```

A version that never becomes ready is caught by a second net. A wrong checksum keeps
`/health/ready` at 503 for ever, so no request is served and the analysis would see nothing at all.
`progressDeadlineSeconds: 600` with `progressDeadlineAbort: true` ends that rollout as well.

## What the chart expects from the rest of the platform

* **Argo Rollouts** is installed in the cluster (component `argo-rollouts`, sync wave 0), so the
  `Rollout` and `AnalysisTemplate` kinds exist.
* **Prometheus** scrapes pods by annotation and adds a `namespace` label. The `kubernetes-pods` job
  of the Prometheus chart does that out of the box. Check the query above in the Prometheus UI once
  after the first deployment: an empty answer is treated as "fine", so a broken scrape config would
  make the analysis pass without looking at anything.
* A scrape interval of 30 s or less. The default of the chart is one minute, which still works with
  the two minute window but makes the analysis slower to react.
* The **ArgoCD Application** passes `imageRegistry`, `mlflowTrackingUri`, `prometheusAddress` and
  `gitSha`. `gitSha` should be set to `$ARGOCD_APP_REVISION`, which ArgoCD replaces with the commit
  it is syncing.
* Namespaces are created by Terraform, so the Applications use `CreateNamespace=false`.

There is no NetworkPolicy in this chart. The cluster runs the VPC CNI without its network policy
support switched on, so a NetworkPolicy would be a document that changes nothing, and a document
that looks like a control is worse than none.

## The first deployment

The very first sync happens when no model has been trained yet. `modelVersion` is empty then, and
three things follow:

* the registry hook is not rendered at all, so nothing claims a production version that does not
  exist;
* the analysis is not rendered either — it can only ask about a version by name;
* the pods fall back to the `staging` alias, so they become ready as soon as the first training run
  registers a model.

The first promotion is then the same one line change as every later one, and it is the first thing
that writes `Production` into MLflow.

## Checking the chart without a cluster

```bash
cd final-project/gitops
REG=111122223333.dkr.ecr.us-east-1.amazonaws.com   # any value, it is only a string here

helm lint charts/inference -f envs/production.yaml --set imageRegistry=$REG
helm template inference-staging charts/inference -n staging \
  -f envs/staging.yaml --set imageRegistry=$REG
helm template inference-production charts/inference -n production \
  -f envs/production.yaml --set imageRegistry=$REG --set gitSha=abc123
```

`kubeconform` checks the result against the real schemas, including the Argo Rollouts CRDs:

```bash
helm template inference-production charts/inference -n production \
  -f envs/production.yaml --set imageRegistry=$REG --set modelVersion=4 \
  | kubeconform -strict -summary -kubernetes-version 1.32.0 \
      -schema-location default \
      -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' -
```
