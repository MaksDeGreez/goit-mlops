# registry-ops

Small command line tool that moves model versions in the MLflow Model Registry. It is the only
place that changes which version is in production, so every change is written down in the same way.

```bash
uv sync
export MLFLOW_TRACKING_URI=http://localhost:5000
uv run python -m registry_ops list
uv run python -m registry_ops promote --version 3
```

In the cluster it runs as a Kubernetes Job: an ArgoCD `PostSync` hook calls
`sync --production-version N` with the version from the production values file, so the registry
always agrees with Git. The hook is `PostSync` and not `PreSync` on purpose: ArgoCD only runs it
after the Application is Healthy, which for a `Rollout` means the canary has finished. A canary that
was aborted therefore leaves the registry naming the old version, which is the truth.

## Commands

| Command | What it does |
|---|---|
| `list` | prints a table of every version with its stage, aliases and tags |
| `promote --version N` | makes N the production version |
| `rollback [--version N]` | goes back to the `previous-production` version, or to N |
| `sync --production-version N` | makes production match N, does nothing when it already does |
| `delete --version N` | removes a version, never the one production runs |

## Settings

| Variable | Option | Default | What it is |
|---|---|---|---|
| `MLFLOW_TRACKING_URI` | `--tracking-uri` | local `./mlruns` | the MLflow server |
| `MODEL_NAME` | `--model-name` | `california-housing` | name in the registry |
| `ACTOR` | `--actor` | `unknown` | who asked for the change |
| `GIT_SHA` | `--git-sha` | `unknown` | the commit that asked for it |

`ACTOR` and `GIT_SHA` only end up in the audit line and in the version tags. The ArgoCD hook passes
the commit it is syncing, so an audit line can always be traced back to a commit.

## The three aliases

* **`staging`** — the newest trained version. The training job sets it and this tool never touches
  it.
* **`production`** — what the production deployment loads.
* **`previous-production`** — the version production used before the last change. It is the rollback
  target.

The old stage names are set next to the aliases: `Production` for the version in production and
`Archived` for the one that left it. Stages are deprecated in MLflow and the call raises a
`FutureWarning`, which the code hides for that one call. They are still set because the assignment
describes the workflow with stage names and because they are the first thing a person sees in the
MLflow UI.

## The rules

**Promote** requires that the version exists and is **not archived**. It does not require the
`Staging` stage: a version loses nothing when a newer one is trained, and promoting a version that
was skipped is normal. An archived version, on the other hand, was already in production once, so
going back to it is a different decision with a different name:

**Rollback** is the only command that accepts an archived version. It also swaps the two aliases:
the version leaving production becomes the new `previous-production`. Running rollback twice
therefore ends where it started.

**Sync** is what the ArgoCD hook runs. It looks at the version Git asks for and chooses:

* it is already in production → `no_change`, nothing is written;
* it is archived → rollback. This is the `git revert` case: reverting a promotion commit puts the
  older version back in the values file, and by then that version is archived. In practice it is the
  `previous-production` one;
* anything else → promote.

**Delete** refuses the version that is in production. For any other version it first removes the
aliases that point at it, because MLflow keeps an alias when the version behind it is deleted and
looking that alias up afterwards fails.

Promoting a version writes three tags on it: `promoted_at`, `promoted_by` and `promoted_git_sha`.
Archiving writes `archived_at`. A version that comes back from a rollback loses `archived_at`
again, because it is in production and the tag would say the opposite.

## Output

**stdout carries the audit lines and nothing else.** One JSON object per line, one line per action.
Everything a person reads — the log and the table of the `list` command — goes to stderr. The rule
is worth the small oddity of a table on stderr: in the cluster this tool is a Job whose stdout is
collected by Loki, and there every line has to parse as JSON.

```json
{"ts": "2026-09-20T20:14:52.317Z", "event": "model_registry_audit", "service": "registry-ops",
 "action": "promote", "model": "california-housing", "version": "3", "from_stage": "Staging",
 "to_stage": "Production", "previous_production_version": "2", "actor": "maks",
 "git_sha": "1f4c9ab", "result": "success", "error": null}
```

`action` is one of `promote`, `rollback`, `archive`, `delete`, `no_change`.
`previous_production_version` is the version the alias `previous-production` points at after the
action, that is what a rollback would bring back.

A command that changes two versions prints two lines, the `archive` line first:

```json
{"action": "archive", "version": "2", "from_stage": "Production", "to_stage": "Archived", ...}
{"action": "promote", "version": "3", "from_stage": "Staging", "to_stage": "Production", ...}
```

A command that is refused prints one line with `"result": "failure"` and the reason in `error`, and
exits with code 1. `list` changes nothing, so it never prints an audit line; when it fails it only
logs and exits 1.

## Why mlflow-skinny

This tool reads and writes tags, stages and aliases. It never opens a model file, so it does not
need pandas, numpy or scikit-learn. `mlflow-skinny` has the same client and is a much smaller
install. The tests need a registry in a SQLite file, and the skinny build does not ship the
database driver for that, so `sqlalchemy` and `alembic` are dev dependencies.

## Tests

```bash
uv run pytest
```

29 tests, about 15 seconds. They run against a registry in a temporary SQLite file with three model
versions that look like the ones the training job leaves behind. The versions point at a folder
that does not exist: no model is ever loaded here, so no model has to be trained for the tests.

The tests cover the first promotion, the second one archiving the first, rollback and the second
rollback undoing it, rollback to a chosen version, sync being idempotent, sync turning into a
rollback for an archived version, the delete guard, promote refusing an archived version, and the
shape of the audit line. The command line tests parse **every** stdout line as JSON, so a stray
print breaks the suite.
