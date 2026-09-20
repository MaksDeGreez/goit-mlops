"""Full training run against a temporary MLflow.

The tracking store is a SQLite file in a temporary folder and the artifacts go
next to it. SQLite is used because the plain file store cannot do model
versions, aliases or stages. The job is started the same way the container
starts it, `python -m training.run`, so the exit code and the JSON line are
tested as well.

The download in these tests is a local copy, not an HTTP download from a
tracking server, so the proxied download path of a real server is not covered
here. What is covered is the part that matters for the contract: the checksum
is computed from the artifact **as the registry stores it** and written to the
tag `model_sha256`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import mlflow
import pytest
from mlflow.tracking import MlflowClient

from training.data import REPO_DATA_PATH, file_sha256
from training.model_hash import model_file_sha256
from training.registry import STAGING_ALIAS, STAGING_STAGE, download_version

SERVICE_ROOT = Path(__file__).resolve().parents[1]
MODEL_NAME = "california-housing-test"
EXPERIMENT_NAME = "california-housing-test"
SAMPLE_ROWS = 500
MAX_ITER = 20

EXPECTED_JSON_KEYS = {
    "event",
    "model",
    "version",
    "run_id",
    "rmse",
    "mae",
    "r2",
    "git_sha",
    "dataset_sha256",
    "model_sha256",
}
EXPECTED_TAGS = {
    "git_sha",
    "dataset_sha256",
    "model_sha256",
    "rmse",
    "mae",
    "r2",
    "run_id",
}


def run_job(tracking_uri: str, *extra: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ, MLFLOW_TRACKING_URI=tracking_uri, GIT_SHA="0123abc")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "training.run",
            "--experiment-name",
            EXPERIMENT_NAME,
            "--model-name",
            MODEL_NAME,
            "--sample-rows",
            str(SAMPLE_ROWS),
            "--max-iter",
            str(MAX_ITER),
            *extra,
        ],
        cwd=SERVICE_ROOT,
        capture_output=True,
        text=True,
        env=environment,
        timeout=300,
    )


@pytest.fixture(scope="module")
def tracking_uri(tmp_path_factory) -> str:
    """A tracking store and an artifact folder that live in a temporary dir."""
    store = tmp_path_factory.mktemp("mlflow")
    uri = f"sqlite:///{store / 'mlflow.db'}"
    MlflowClient(tracking_uri=uri).create_experiment(
        EXPERIMENT_NAME, artifact_location=str(store / "artifacts")
    )
    return uri


@pytest.fixture(scope="module")
def client(tracking_uri: str) -> MlflowClient:
    return MlflowClient(tracking_uri=tracking_uri, registry_uri=tracking_uri)


@pytest.fixture(scope="module")
def first_result(tracking_uri: str) -> dict:
    finished = run_job(tracking_uri)
    assert finished.returncode == 0, finished.stderr
    return json.loads(finished.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def second_result(tracking_uri: str, first_result: dict) -> dict:
    finished = run_job(tracking_uri)
    assert finished.returncode == 0, finished.stderr
    return json.loads(finished.stdout.strip().splitlines()[-1])


def test_the_job_prints_one_json_line_with_the_agreed_fields(first_result):
    assert set(first_result) == EXPECTED_JSON_KEYS
    assert first_result["event"] == "training_finished"
    assert first_result["model"] == MODEL_NAME
    assert first_result["version"] == "1"
    assert first_result["git_sha"] == "0123abc"
    assert first_result["dataset_sha256"] == file_sha256(REPO_DATA_PATH)
    assert 0.0 < first_result["rmse"] < 5.0
    assert first_result["mae"] <= first_result["rmse"]


def test_the_run_is_in_the_experiment_with_its_metrics(client, first_result):
    run = client.get_run(first_result["run_id"])

    assert run.info.status == "FINISHED"
    assert run.data.metrics["rmse"] == pytest.approx(first_result["rmse"])
    assert run.data.metrics["mae"] == pytest.approx(first_result["mae"])
    assert run.data.metrics["r2"] == pytest.approx(first_result["r2"])
    assert run.data.params["max_iter"] == str(MAX_ITER)
    assert run.data.params["rows"] == str(SAMPLE_ROWS)
    assert run.data.tags["git_sha"] == "0123abc"
    assert run.data.tags["dataset_sha256"] == first_result["dataset_sha256"]


def test_the_new_version_carries_every_tag(client, first_result):
    version = client.get_model_version(MODEL_NAME, first_result["version"])

    assert set(version.tags) >= EXPECTED_TAGS
    assert version.tags["run_id"] == first_result["run_id"]
    assert version.tags["model_sha256"] == first_result["model_sha256"]
    assert float(version.tags["rmse"]) == pytest.approx(first_result["rmse"], abs=1e-6)


def test_the_new_version_gets_the_staging_alias_and_stage(client, first_result):
    by_alias = client.get_model_version_by_alias(MODEL_NAME, STAGING_ALIAS)

    # MLflow returns the version as a number, the JSON line uses a string.
    assert str(by_alias.version) == first_result["version"]
    assert client.get_model_version(MODEL_NAME, first_result["version"]).current_stage == (
        STAGING_STAGE
    )


def test_the_model_sha256_tag_matches_the_downloaded_model(tracking_uri, first_result, tmp_path):
    """Download the version again and hash it, the way inference will."""
    mlflow.set_tracking_uri(tracking_uri)
    model_dir = download_version(MODEL_NAME, first_result["version"], tmp_path / "download")

    assert (model_dir / "MLmodel").is_file()
    assert model_file_sha256(model_dir) == first_result["model_sha256"]
    assert len(first_result["model_sha256"]) == 64


def test_a_second_run_creates_a_new_version_and_moves_the_alias(
    client, first_result, second_result
):
    assert second_result["version"] == "2"
    assert second_result["run_id"] != first_result["run_id"]
    assert str(client.get_model_version_by_alias(MODEL_NAME, STAGING_ALIAS).version) == "2"
    assert client.get_model_version(MODEL_NAME, "2").current_stage == STAGING_STAGE


def test_the_same_data_gives_the_same_metrics_in_a_second_run(first_result, second_result):
    assert second_result["rmse"] == first_result["rmse"]
    assert second_result["mae"] == first_result["mae"]
    assert second_result["r2"] == first_result["r2"]
    assert second_result["dataset_sha256"] == first_result["dataset_sha256"]


def test_the_job_fails_with_a_non_zero_exit_code_when_the_data_is_missing(tracking_uri, tmp_path):
    finished = run_job(tracking_uri, "--data-path", str(tmp_path / "missing.csv"))

    assert finished.returncode == 1
    assert finished.stdout.strip() == ""
    assert "missing.csv" in finished.stderr
