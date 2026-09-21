# Architecture decision record

One page on the deployment strategy, plus short notes on the other decisions
that shaped the project.

## Context

The system serves one scikit-learn regression model behind a FastAPI service.
A new model version appears whenever the training pipeline runs, which can be
several times a day. Staging follows the newest version by itself; production
must only ever change when a person asks for it, and that change has to be
visible, reversible and safe.

The platform is small on purpose:

- One EKS cluster, two `t4g.large` nodes. Measured allocatable: 1930m CPU and
  about 6.9 GiB per node, so roughly 3.8 CPUs and 13 GiB for pods in total.
- Nothing is public. There is no ingress controller, no load balancer, no
  domain and no TLS certificate. Everything is reached with `kubectl
  port-forward`.
- The whole cluster is created and destroyed again in every working session,
  because there is no free tier on this AWS account.
- One person operates it.

Those four facts decided more than anything else.

## Decision

**Production uses a canary rollout driven by Argo Rollouts, with the traffic
share expressed as a share of the pods, and an automatic abort when the new
version returns too many server errors.**

The `Rollout` object replaces the `Deployment` in
`gitops/charts/inference`. Production runs 10 replicas and the steps are
`setWeight 10 → pause 120s → setWeight 50 → pause 120s → (100 %)`. A background
`AnalysisTemplate` queries Prometheus every 30 seconds for the share of 5xx
answers of the **new** model version only, and the third failed measurement in
a row aborts the rollout and scales the new pods back to zero.

There is no traffic router. One `ClusterIP` Service sits in front of every pod
of the release, old and new, and Kubernetes spreads requests over the ready
endpoints. With 10 replicas, "10 %" is literally one new pod next to nine old
ones.

### What it did in practice

The decision was tested on the running cluster, three times, with traffic at
about 10 requests per second.

| Run | Result | Time |
|---|---|---|
| promote version 1 | Healthy, 9 good measurements | about 5 minutes |
| promote version 2, then `git revert` | Healthy both ways, registry followed | about 5 minutes each |
| promote version 2 with `faultRate: 0.5` | **aborted by itself** after 3 failed measurements (0.548, 0.583, 0.572 against a limit of 0.05) | about 2 minutes |

The number that matters is how much of the traffic ever saw the broken version.
One canary pod out of eleven, failing half of its requests, showed up as
**2.08 % of 5xx for the whole service, for about two minutes**. That is the
cost of the strategy, measured instead of estimated: a Blue-Green switch would
have put the same broken version on 100 % of the requests.

### Why canary and not something else

| Option | Why not |
|---|---|
| **Blue-Green** | Needs a second full copy of the service. Ten more pods at 256Mi would be 2.5 GiB of extra memory requests on a cluster that has about 13 GiB and is already two thirds full, and the switch is all-or-nothing: the first request a broken version sees is 100 % of the traffic. |
| **A/B testing** | Compares two models on a business metric. That needs labels, a feedback loop and a lot of traffic. This project has synthetic traffic from a script, so the comparison would not mean anything. |
| **Canary with a real traffic router** | The clean way to get an exact 10 % split. It needs an ingress controller or a service mesh. `ingress-nginx` was archived in March 2026 and gets no fixes, the Argo Rollouts Gateway API plugin is still alpha, and an ALB would cost money and put the service on the public internet, which this project deliberately avoids. |
| **Plain rolling update** | What staging uses, and it is right there. It cannot pause, cannot measure anything and cannot roll itself back, so it is not enough for production. |

Canary with replica-based weights gives the two things the assignment asks for
— a gradual 90/10 split and an automatic rollback — with no extra
infrastructure at all.

## Trade-offs accepted

- **The split is approximate.** "10 %" is one pod out of ten, not 10 % of the
  requests. Keep-alive connections and uneven request cost make the real share
  wobble around that number. For a demonstration this is close enough; for a
  service with real money on it, it would not be.
- **It only works with enough replicas.** 10 replicas exist so that one of them
  is 10 %. That is more pods than this traffic needs. `maxSurge: 1` and
  `maxUnavailable: 0` keep the step honest: with `maxSurge: 2` the first step
  would already serve 20 %.
- **No traffic means no signal.** If nobody calls `/predict` during the canary,
  the analysis has nothing to measure. The query is written to treat "no data"
  as success, because the alternative — aborting every rollout that happens at
  a quiet moment — is worse. The price is that a broken Prometheus looks like a
  healthy canary. The `faultRate` switch exists so the guard can be shown to
  work on purpose.
- **The registry is updated only after the canary.** The hook Job that moves the
  MLflow alias and stage is a `PostSync` hook, and Argo CD runs those only when
  the Application is Healthy, which for a `Rollout` means the canary finished.
  So there is a window of a few minutes in which Git says version 4 and the
  registry still says version 3. That is the honest state: version 3 is what
  most pods are still serving. An aborted canary leaves the registry at
  version 3 for good, which is also the truth.
- **Production is pinned twice, staging is not pinned at all.** Production
  names a version number *and* a SHA-256 in Git; the pod refuses to become
  ready if the file it downloads does not hash to that value. Staging follows
  the alias `staging` and reloads by itself. Two different promises: staging is
  always newest, production is always exactly what was reviewed.

## Other decisions, in short

- **Two Terraform stacks, not one.** `stacks/infra` (VPC, EKS, ECR, the CI
  role) and `stacks/platform` (namespaces, secrets, MLflow, Step Functions,
  Argo CD), linked by `terraform_remote_state`. The Kubernetes and Helm
  providers of the second stack need a cluster that already exists; in one
  stack Terraform would have to plan against a cluster it has not created yet.
- **Terraform owns AWS and the secrets, Argo CD owns the charts.** The two
  generated passwords are `random_password` resources written straight into
  Kubernetes Secrets, and the charts read them with `existingSecret`. No
  password is in Git and no chart is installed by hand.
- **The ECR registry host is injected, never committed.** It contains the AWS
  account id and this repository is public. Terraform passes it to the root
  Application, which passes it down to the charts.
- **MLflow aliases *and* stages.** Aliases (`staging`, `production`,
  `previous-production`) are what the code reads. The deprecated stages
  (`Staging`, `Production`, `Archived`) are set as well, because the assignment
  describes the workflow in those words and the MLflow UI still shows them.
- **Port-forward instead of Ingress.** Nothing is public, so there is no attack
  surface on the internet, no certificate to manage and no load balancer to pay
  for. MLflow and the Prometheus UI have no login of their own, so making them
  public would mean putting authentication in front of them first. The cost is
  that a reviewer needs `kubectl` and the README instead of a link.
- **GitHub Actions is the real pipeline.** The assignment asks for GitLab CI.
  There is no GitLab account and the repository is on GitHub, so the project
  ships a working GitHub Actions pipeline *and* an equivalent `.gitlab-ci.yml`
  that was run locally with `gitlab-ci-local`. The same pair was accepted in an
  earlier assignment.
- **Step Functions starts a Kubernetes Job.** Training runs where the data and
  MLflow are, inside the cluster, but it is started from outside it, so CI needs
  no cluster credentials — only `states:StartExecution`. The state machine uses
  `eks:runJob.sync`, waits for the Job and brings the last log lines back, and a
  small Lambda picks the `training_finished` JSON line out of them.
- **Loki is the source for the drift job.** The inference service already logs
  every prediction as JSON, so the drift job reads those lines back instead of
  the project keeping a second copy of the features in a database.

## What we learned by running it

Three things only became clear once the system was on AWS and the canary had
run for real. None of them changes the decision, but all three change how the
strategy is operated, and they are in the runbook now.

- **The blind spot is real, and easy to walk into.** A port-forward connects to
  one pod, so the first attempt to "send traffic during a canary" put every
  request on a single pod and the analysis measured nothing useful. Traffic for
  a canary has to come from inside the cluster. A rollout at a quiet moment
  still passes on no data, and that is accepted on purpose — but it means the
  guard is only as good as the traffic, and a demo without traffic proves
  nothing.
- **An abort is not the end of the story.** After the rollout aborted, Argo CD
  kept retrying the failed sync (five attempts, five to eight minutes) before
  it even looked at the `git revert` that was already pushed. Production was
  safe the whole time, but "revert and it is fixed" is not instant. Pressing
  **Terminate** on the running operation skips the wait.
- **The replica split is approximate, and the numbers show it.** At the 10 %
  step the new pod did not get exactly a tenth of the requests, and the error
  share the dashboard reported (2.08 %) is close to, but not the same as, the
  arithmetic 5 %. Good enough to decide "abort", not good enough to compare two
  models on quality.

## What would be done differently with more time

- A real traffic router — Gateway API once the Argo Rollouts plugin is stable —
  so the canary weight is a true share of the requests and 10 replicas are no
  longer needed to express 10 %.
- `NetworkPolicy` objects. Today any pod can reach MLflow and Postgres; only
  the fact that nothing is public keeps that small.
- Kubernetes secret encryption with a customer-managed KMS key, which the
  cluster deliberately does without to keep the bill down.
- Single sign-on for Argo CD and Grafana instead of a generated admin password,
  and real RBAC in Argo CD instead of `role:readonly` for everyone.
- An alert route that goes somewhere. The Grafana contact point is a
  placeholder address and no SMTP server is configured, so an alert is only
  visible in the Grafana UI.
- A managed database. Postgres is a single pod with one PVC; if the node it
  sits on goes away, MLflow is down until it is rescheduled. RDS would fix that
  for about $15 a month.
- Signed images and a policy that refuses unsigned ones. Today the chain of
  trust is "CI built it and the tag is immutable".
- Separate clusters for staging and production instead of separate namespaces.
  Namespaces are the honest choice at this size, but they share a control
  plane, the nodes and the CNI.

## Where to read more

- Deployment, namespaces, promotion and rollback: [`README.md`](README.md)
- The three runs above, with the screenshots:
  [`docs/demo-trace.md`](docs/demo-trace.md)
- What to do when something breaks: [`RUNBOOK.md`](RUNBOOK.md)
- Attack surface and controls: [`docs/threat-model.md`](docs/threat-model.md)
- The chart that implements all of this:
  [`gitops/charts/inference/README.md`](gitops/charts/inference/README.md)
