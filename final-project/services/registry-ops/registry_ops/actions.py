"""The rules of the promotion workflow.

The registry has three aliases that matter:

* `staging` — the newest trained version. The training job sets it, nothing
  here ever touches it;
* `production` — the version the production deployment loads;
* `previous-production` — the version production used before the last change.
  It is the rollback target.

Every function returns the audit lines of what it did, in the order it did it.
A rule that says no raises `ActionError`; the caller turns that into one audit
line with `result: failure` and a non-zero exit code.
"""

from __future__ import annotations

from mlflow.tracking import MlflowClient

from registry_ops.audit import audit_line, utc_now_iso
from registry_ops.registry import (
    ARCHIVED_STAGE,
    PREVIOUS_PRODUCTION_ALIAS,
    PRODUCTION_ALIAS,
    PRODUCTION_STAGE,
    Settings,
    alias_version,
    aliases_of_model,
    all_versions,
    delete_version,
    drop_aliases_of_version,
    get_version,
    set_alias,
    set_stage,
    set_version_tags,
)

PROMOTE = "promote"
ROLLBACK = "rollback"
ARCHIVE = "archive"
DELETE = "delete"
NO_CHANGE = "no_change"


class ActionError(RuntimeError):
    """The command cannot be carried out. The message goes into the audit line."""


def production_version(client: MlflowClient, model: str) -> str | None:
    return alias_version(client, model, PRODUCTION_ALIAS)


def previous_production_version(client: MlflowClient, model: str) -> str | None:
    return alias_version(client, model, PREVIOUS_PRODUCTION_ALIAS)


def _require_stage(client: MlflowClient, model: str, version: str) -> str:
    """The current stage of a version, or an error when it does not exist."""
    found = get_version(client, model, version)
    if found is None:
        raise ActionError(f"version {version} of model {model} does not exist")
    return found.current_stage


def _line(settings: Settings, action: str, version: str | None, **fields: object) -> dict:
    return audit_line(
        action,
        settings.model_name,
        version,
        actor=settings.actor,
        git_sha=settings.git_sha,
        **fields,
    )


def _archive(client: MlflowClient, settings: Settings, version: str) -> dict:
    """Retire the version that is leaving production and keep it reachable.

    It becomes the rollback target: stage `Archived`, alias
    `previous-production`, plus the time it happened.
    """
    model = settings.model_name
    from_stage = _require_stage(client, model, version)
    set_stage(client, model, version, ARCHIVED_STAGE)
    set_version_tags(client, model, version, {"archived_at": utc_now_iso()})
    set_alias(client, model, PREVIOUS_PRODUCTION_ALIAS, version)
    return _line(
        settings,
        ARCHIVE,
        version,
        from_stage=from_stage,
        to_stage=ARCHIVED_STAGE,
        previous_production_version=version,
    )


def _make_production(
    client: MlflowClient,
    settings: Settings,
    version: str,
    *,
    action: str,
    from_stage: str,
    previous: str | None,
) -> dict:
    """Give the version the production alias, the stage and the tags."""
    model = settings.model_name
    set_alias(client, model, PRODUCTION_ALIAS, version)
    set_stage(client, model, version, PRODUCTION_STAGE)
    set_version_tags(
        client,
        model,
        version,
        {
            "promoted_at": utc_now_iso(),
            "promoted_by": settings.actor,
            "promoted_git_sha": settings.git_sha,
        },
    )
    return _line(
        settings,
        action,
        version,
        from_stage=from_stage,
        to_stage=PRODUCTION_STAGE,
        previous_production_version=previous,
    )


def _no_change(client: MlflowClient, settings: Settings, version: str) -> list[dict]:
    return [
        _line(
            settings,
            NO_CHANGE,
            version,
            from_stage=PRODUCTION_STAGE,
            to_stage=PRODUCTION_STAGE,
            previous_production_version=previous_production_version(client, settings.model_name),
        )
    ]


def _switch_production(
    client: MlflowClient, settings: Settings, version: str, action: str
) -> list[dict]:
    """Move production to `version`, archiving the version that held it.

    Used by both `promote` and `rollback`; only the name in the audit line
    differs.
    """
    model = settings.model_name
    from_stage = _require_stage(client, model, version)
    current = production_version(client, model)
    if current == version:
        return _no_change(client, settings, version)

    lines = []
    if current is not None:
        lines.append(_archive(client, settings, current))
    lines.append(
        _make_production(
            client,
            settings,
            version,
            action=action,
            from_stage=from_stage,
            previous=current,
        )
    )
    return lines


def promote(client: MlflowClient, settings: Settings, version: str) -> list[dict]:
    """Make a version the production one.

    Promotion only moves forward. An archived version was in production before
    and coming back to it is a different decision, so `promote` refuses it and
    `rollback` does that job. The version does not have to be in `Staging`:
    the training job sets that stage, but a version can lose it when a newer
    one is trained, and promoting a version that was skipped is a normal thing
    to do.
    """
    if _require_stage(client, settings.model_name, version) == ARCHIVED_STAGE:
        raise ActionError(
            f"version {version} is archived, use rollback to bring it back to production"
        )
    return _switch_production(client, settings, version, PROMOTE)


def rollback(client: MlflowClient, settings: Settings, version: str | None = None) -> list[dict]:
    """Go back to the version production used before, or to a given version.

    The version that is in production now becomes the new rollback target, so
    running rollback twice ends where it started.
    """
    model = settings.model_name
    target = version or previous_production_version(client, model)
    if target is None:
        raise ActionError(
            f"model {model} has no {PREVIOUS_PRODUCTION_ALIAS} version to roll back to"
        )
    return _switch_production(client, settings, target, ROLLBACK)


def sync(client: MlflowClient, settings: Settings, version: str) -> list[dict]:
    """Make the registry match what Git says production should be.

    An ArgoCD hook runs this on every sync, so it has to be idempotent: when
    the version is already the production one it only logs `no_change`.

    A `git revert` of a promotion commit puts an older version back into the
    values file. That version is archived by then, which is exactly the
    rollback case, so `sync` calls rollback for any archived target. In
    practice the target is the `previous-production` version.
    """
    stage = _require_stage(client, settings.model_name, version)
    if production_version(client, settings.model_name) == version:
        return _no_change(client, settings, version)
    if stage == ARCHIVED_STAGE:
        return rollback(client, settings, version)
    return promote(client, settings, version)


def delete(client: MlflowClient, settings: Settings, version: str) -> list[dict]:
    """Remove a version from the registry, never the one production runs."""
    model = settings.model_name
    stage = _require_stage(client, model, version)
    current = production_version(client, model)
    if current == version:
        raise ActionError(f"version {version} is in production and cannot be deleted")

    drop_aliases_of_version(client, model, version)
    delete_version(client, model, version)
    return [
        _line(
            settings,
            DELETE,
            version,
            from_stage=stage,
            to_stage=None,
            previous_production_version=previous_production_version(client, model),
        )
    ]


def list_versions(client: MlflowClient, model: str) -> list[dict[str, str]]:
    """One row per version for the table the `list` command prints."""
    by_version: dict[str, list[str]] = {}
    for alias, target in aliases_of_model(client, model).items():
        by_version.setdefault(target, []).append(alias)

    versions = all_versions(client, model)
    if not versions:
        raise ActionError(f"model {model} has no versions, or does not exist")

    rows = []
    for found in versions:
        version = str(found.version)
        tags = found.tags or {}
        rows.append(
            {
                "version": version,
                "stage": found.current_stage,
                "aliases": ",".join(sorted(by_version.get(version, []))) or "-",
                "rmse": tags.get("rmse", "-"),
                "git_sha": tags.get("git_sha", "-")[:8],
                "model_sha256": tags.get("model_sha256", "-")[:12],
                "run_id": tags.get("run_id", "-")[:12],
            }
        )
    return rows
