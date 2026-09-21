# RBAC

Who may do what inside the cluster. Plain manifests, applied by ArgoCD as a directory (sync wave 0,
before anything else is deployed).

| Files | What is in them |
|---|---|
| `0*-clusterrole-*.yaml` | the six roles. All of them are ClusterRoles; five are bound per namespace |
| `1*`, `20-` | the bindings of the group `mlops-engineers` |
| `3*` | the bindings of the group `viewers` |
| `40-` | the binding of the group `stepfunctions-runners` |
| `50-` | the `training` service account |

One object per file, and the numbers only put the directory in a readable order. The repository
checks every committed YAML file with `check-yaml`, and that hook refuses a file with more than one
document. So the usual "all the bindings in one file" layout is not possible here. That is not a
problem: a change to one binding is a change to one file.

The namespaces themselves are created by Terraform, so there is no `Namespace` object here.

## The three groups

Nobody is named in these files. A person gets a role by assuming an IAM role. An EKS access entry,
created by Terraform, says which Kubernetes group that IAM role belongs to. The cluster only ever
sees the group name.

| Kubernetes group | IAM role | Who |
|---|---|---|
| `mlops-engineers` | `mlops-final-mlops-engineer` | the people who build and run the platform |
| `viewers` | `mlops-final-viewer` | anyone who has to look but not touch |
| `stepfunctions-runners` | the Step Functions state machine role | the training pipeline |

The access entries are of the plain `STANDARD` type with no AWS access policy attached. So the
rules in this directory are the only permissions these roles have.

## The permission matrix

| | `staging` | `production` | `mlops-system` | `monitoring` | `argocd` | cluster wide |
|---|---|---|---|---|---|---|
| **mlops-engineers** | everything, Secrets and `exec` included | read, port-forward, `patch rollouts/status` | read, port-forward | read, port-forward | read, port-forward | read namespaces, nodes, storage classes, CRDs |
| **viewers** | read | read | read | read | read | read namespaces, nodes, storage classes, CRDs |
| **stepfunctions-runners** | — | — | `jobs` get/list/watch/create/delete, `pods` and `pods/log` read | — | — | — |

"read" always means the same role, `mlops-final-viewer`. It gives `get`, `list` and `watch` on pods
and their logs, services, configmaps, events, PVCs, service accounts, deployments, replicasets,
statefulsets, daemonsets, jobs, cronjobs, ingresses, network policies, PDBs, HPAs, the Argo Rollouts
objects, the ArgoCD Applications, and `kubectl top pods`. Secrets are in none of these roles, and
neither is `pods/exec`.

## Two decisions explained

**Why an engineer cannot change production, but can stop a canary.**

What runs in production comes from a commit in this repository. An engineer who could `patch` the
Rollout could change the image or the model version without a commit. ArgoCD would put it back a
minute later, but by then the audit trail would already be wrong. So `patch` on `rollouts` is not
granted.

`patch` on `rollouts/status` is granted. That is what `kubectl argo rollouts abort` and
`kubectl argo rollouts promote` actually send: a merge patch to the status subresource. This was
checked in the Argo Rollouts source for v1.10.0. Aborting a bad canary, or letting a good one skip
the rest of its pauses, changes the progress of a rollout and not what is deployed. The spec stays
exactly what git says. A canary that is aborted this way goes back to the old version, which is the
state git already describes.

The one command this costs is `kubectl argo rollouts pause`, which patches `spec.paused`. That is
on purpose: pausing a rollout for ever is a change to what is deployed.

**Why nobody reads Secrets.** The Secrets in these namespaces hold the Postgres password of MLflow
and the Grafana admin password. Terraform generates both with `random_password` and writes them
straight into the cluster. There is no copy to lose and no reason for a person to read one. The
pods that need them get them mounted.

## Service accounts

`training` in `mlops-system`, with no RoleBinding at all. The training job reads the CSV inside its
image and talks to MLflow over HTTP, so it needs nothing from the Kubernetes API. Its token is not
mounted either.

The `mlflow` service account of the same namespace is **not** created here, even though it belongs
to the same picture. The MLflow chart creates it (`serviceAccount.name: mlflow`), and Terraform
attaches an EKS Pod Identity to it for the artifact bucket. If this directory created it as well,
ArgoCD and the chart would own the same object and overwrite each other on every sync.

## Proof: `kubectl auth can-i`

`scripts/check_rbac.sh` runs every line of the tables below against the cluster. It compares each
answer with the expected one. Subresources are written with `--subresource=`. The short form
`pods/portforward` is answered with "no" by kubectl for some verbs even when the rule exists.

It was run against the deployed cluster, and all 32 answers matched this file, denials included.
The script exits non-zero on the first mismatch, so it also works as a check after a change here.

Run these with an account that may impersonate (the cluster creator). The expected answer is next
to each line. The denials matter as much as the allowances.

```bash
E="--as=test --as-group=mlops-engineers"
V="--as=test --as-group=viewers"
S="--as=test --as-group=stepfunctions-runners"
```

**mlops-engineer, staging: everything**

| Command | Expected |
|---|---|
| `kubectl auth can-i create rollouts.argoproj.io -n staging $E` | yes |
| `kubectl auth can-i delete pods -n staging $E` | yes |
| `kubectl auth can-i get secrets -n staging $E` | yes |
| `kubectl auth can-i create pods --subresource=exec -n staging $E` | yes |

**mlops-engineer, production: limited**

| Command | Expected |
|---|---|
| `kubectl auth can-i get pods -n production $E` | yes |
| `kubectl auth can-i get pods --subresource=log -n production $E` | yes |
| `kubectl auth can-i create pods --subresource=portforward -n production $E` | yes |
| `kubectl auth can-i patch rollouts.argoproj.io --subresource=status -n production $E` | yes |
| `kubectl auth can-i get secrets -n production $E` | **no** |
| `kubectl auth can-i patch rollouts.argoproj.io -n production $E` | **no** |
| `kubectl auth can-i delete rollouts.argoproj.io -n production $E` | **no** |
| `kubectl auth can-i create pods --subresource=exec -n production $E` | **no** |
| `kubectl auth can-i delete pods -n production $E` | **no** |

**mlops-engineer, the platform namespaces**

| Command | Expected |
|---|---|
| `kubectl auth can-i get pods --subresource=log -n mlops-system $E` | yes |
| `kubectl auth can-i create pods --subresource=portforward -n monitoring $E` | yes |
| `kubectl auth can-i get applications.argoproj.io -n argocd $E` | yes |
| `kubectl auth can-i create jobs -n mlops-system $E` | **no** |
| `kubectl auth can-i get secrets -n mlops-system $E` | **no** |

**viewer: read only**

| Command | Expected |
|---|---|
| `kubectl auth can-i get pods -n production $V` | yes |
| `kubectl auth can-i get pods --subresource=log -n production $V` | yes |
| `kubectl auth can-i get rollouts.argoproj.io -n production $V` | yes |
| `kubectl auth can-i get applications.argoproj.io -n argocd $V` | yes |
| `kubectl auth can-i get secrets -n production $V` | **no** |
| `kubectl auth can-i create pods --subresource=portforward -n staging $V` | **no** |
| `kubectl auth can-i create pods --subresource=exec -n production $V` | **no** |
| `kubectl auth can-i delete pods -n staging $V` | **no** |
| `kubectl auth can-i patch applications.argoproj.io -n argocd $V` | **no** |

**stepfunctions-runner: one namespace, one job**

| Command | Expected |
|---|---|
| `kubectl auth can-i create jobs -n mlops-system $S` | yes |
| `kubectl auth can-i delete jobs -n mlops-system $S` | yes |
| `kubectl auth can-i get pods --subresource=log -n mlops-system $S` | yes |
| `kubectl auth can-i create jobs -n production $S` | **no** |
| `kubectl auth can-i get secrets -n mlops-system $S` | **no** |

The whole list of one role, for a screenshot:

```bash
kubectl auth can-i --list -n production --as=test --as-group=mlops-engineers
```

## Checking the manifests without a cluster

```bash
cd final-project
kubeconform -strict -summary -kubernetes-version 1.35.0 -schema-location default rbac/*.yaml
```
