"""A small registry in a temporary SQLite file.

The tests need model versions, not models: every action of this tool works on
tags, stages and aliases and never opens the model file. So the versions point
at a folder that does not exist, which keeps the whole suite at a few seconds.

SQLite is used because the plain file store cannot do model versions, aliases
or stages.
"""

from __future__ import annotations

import pytest
from mlflow.tracking import MlflowClient

from registry_ops.registry import STAGING_ALIAS, STAGING_STAGE, Settings, set_stage

MODEL = "california-housing-test"
VERSION_COUNT = 3


@pytest.fixture
def tracking_uri(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'registry.db'}"


@pytest.fixture
def settings() -> Settings:
    return Settings(model_name=MODEL, actor="maks", git_sha="0123abc")


@pytest.fixture
def client(tracking_uri: str, tmp_path) -> MlflowClient:
    """Three trained versions, the way the training job leaves them."""
    client = MlflowClient(tracking_uri=tracking_uri, registry_uri=tracking_uri)
    client.create_registered_model(MODEL)

    for number in range(1, VERSION_COUNT + 1):
        version = str(
            client.create_model_version(MODEL, source=f"file://{tmp_path}/model-{number}").version
        )
        for key, value in {
            "git_sha": f"sha{number}0000000",
            "dataset_sha256": "d" * 64,
            "model_sha256": f"{number}" * 64,
            "rmse": f"0.{number}00000",
            "mae": f"0.{number}00000",
            "r2": f"0.9{number}0000",
            "run_id": f"run{number}" + "0" * 27,
        }.items():
            client.set_model_version_tag(MODEL, version, key, value)
        client.set_registered_model_alias(MODEL, STAGING_ALIAS, version)
        set_stage(client, MODEL, version, STAGING_STAGE)

    return client
