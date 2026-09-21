"""Small helpers around the MLflow client.

Nothing here decides anything: these functions only read and write the registry.
The rules live in `actions.py`.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

from mlflow.entities.model_registry import ModelVersion
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

PRODUCTION_ALIAS = "production"
PREVIOUS_PRODUCTION_ALIAS = "previous-production"
STAGING_ALIAS = "staging"

PRODUCTION_STAGE = "Production"
STAGING_STAGE = "Staging"
ARCHIVED_STAGE = "Archived"
NO_STAGE = "None"


@dataclass(frozen=True)
class Settings:
    """Everything a command needs besides its own options."""

    model_name: str
    actor: str
    git_sha: str


def set_stage(client: MlflowClient, model: str, version: str, stage: str) -> None:
    """Move a version to an old style stage.

    Stages are deprecated in MLflow and the call raises a `FutureWarning`. They
    are still set because the assignment describes the workflow with stage
    names and they are the first thing a reviewer sees in the UI. The aliases
    next to them are what the services really read.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=".*transition_model_version_stage.*",
            category=FutureWarning,
        )
        client.transition_model_version_stage(model, version, stage)


def get_version(client: MlflowClient, model: str, version: str) -> ModelVersion | None:
    """The version, or None when there is no such version."""
    try:
        return client.get_model_version(model, version)
    except MlflowException:
        return None


def alias_version(client: MlflowClient, model: str, alias: str) -> str | None:
    """Which version an alias points at, or None when the alias is not set."""
    try:
        return str(client.get_model_version_by_alias(model, alias).version)
    except MlflowException:
        return None


def aliases_of_model(client: MlflowClient, model: str) -> dict[str, str]:
    """Every alias of the model as `alias -> version`."""
    try:
        aliases = client.get_registered_model(model).aliases or {}
    except MlflowException:
        return {}
    return {alias: str(version) for alias, version in aliases.items()}


def set_alias(client: MlflowClient, model: str, alias: str, version: str) -> None:
    client.set_registered_model_alias(model, alias, version)


def drop_aliases_of_version(client: MlflowClient, model: str, version: str) -> list[str]:
    """Remove every alias that points at a version and return their names.

    MLflow keeps the alias when the version behind it is deleted, and looking
    the alias up afterwards fails. So the aliases are removed first.
    """
    removed = []
    for alias, target in aliases_of_model(client, model).items():
        if target == version:
            client.delete_registered_model_alias(model, alias)
            removed.append(alias)
    return removed


def set_version_tags(client: MlflowClient, model: str, version: str, tags: dict[str, str]) -> None:
    for key, value in tags.items():
        client.set_model_version_tag(model, version, key, str(value))


def clear_version_tag(client: MlflowClient, model: str, version: str, key: str) -> None:
    """Remove a tag if the version has it."""
    found = get_version(client, model, version)
    if found is not None and key in (found.tags or {}):
        client.delete_model_version_tag(model, version, key)


def delete_version(client: MlflowClient, model: str, version: str) -> None:
    client.delete_model_version(model, version)


def all_versions(client: MlflowClient, model: str) -> list[ModelVersion]:
    """Every version of the model, newest first."""
    versions = client.search_model_versions(f"name='{model}'", order_by=["version_number DESC"])
    return list(versions)
