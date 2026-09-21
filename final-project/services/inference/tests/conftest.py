"""Shared test helpers.

The tests never touch the network. A tiny real scikit-learn model is saved
once in MLflow's own format, and a fake source hands that folder out instead
of downloading it from a tracking server. Everything after the download is
therefore the real code: the checksum, the deserialization and the prediction.
"""

from __future__ import annotations

import io
import json
import logging
import shutil
from pathlib import Path

import mlflow.sklearn
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from inference.logging_setup import configure_logging
from inference.model_hash import model_file_sha256
from inference.model_store import VersionInfo
from inference.schemas import FEATURE_COLUMNS

GIT_SHA = "0123abcdef"
RUN_ID = "11112222333344445555666677778888"

VALID_REQUEST = {
    "MedInc": 8.3252,
    "HouseAge": 41.0,
    "AveRooms": 6.9841,
    "AveBedrms": 1.0238,
    "Population": 322.0,
    "AveOccup": 2.5556,
    "Latitude": 37.88,
    "Longitude": -122.23,
}


def _training_frame(rows: int = 50) -> pd.DataFrame:
    generator = np.random.default_rng(seed=7)
    return pd.DataFrame(
        generator.uniform(1.0, 5.0, size=(rows, len(FEATURE_COLUMNS))),
        columns=FEATURE_COLUMNS,
    )


@pytest.fixture(scope="session")
def saved_model_dir(tmp_path_factory) -> Path:
    """A real MLflow model folder with a very small pipeline inside."""
    features = _training_frame()
    target = features["MedInc"] * 0.5 + 1.0

    pipeline = Pipeline(
        [("scale", StandardScaler()), ("model", LinearRegression())],
    ).fit(features, target)

    model_dir = tmp_path_factory.mktemp("model") / "model"
    mlflow.sklearn.save_model(
        pipeline,
        str(model_dir),
        serialization_format="cloudpickle",
        # Listing them by hand keeps MLflow from reading the whole environment,
        # which would make every test run several seconds slower.
        pip_requirements=["scikit-learn", "pandas"],
    )
    return model_dir


@pytest.fixture(scope="session")
def saved_model_sha256(saved_model_dir: Path) -> str:
    return model_file_sha256(saved_model_dir)


class LogReader:
    """Reads back the JSON lines the service logged during a test."""

    def __init__(self, stream: io.StringIO) -> None:
        self._stream = stream

    def lines(self) -> list[dict]:
        return [json.loads(line) for line in self._stream.getvalue().splitlines() if line]

    def events(self, event: str) -> list[dict]:
        return [line for line in self.lines() if line.get("event") == event]

    def last(self, event: str) -> dict:
        found = self.events(event)
        assert found, f"no {event} event in the log"
        return found[-1]


@pytest.fixture
def log_reader():
    """Catch the log in memory instead of on stdout."""
    stream = io.StringIO()
    configure_logging("DEBUG", stream)
    yield LogReader(stream)
    logging.getLogger().handlers = []


class FakeSource:
    """A model source that copies a local folder instead of downloading it."""

    def __init__(self, model_dir: Path, checksum: str, version: str = "1") -> None:
        self.model_dir = model_dir
        self.version = version
        self.tags = {"model_sha256": checksum, "git_sha": GIT_SHA, "run_id": RUN_ID}
        self.resolve_calls = 0
        self.download_calls = 0
        # Set these to make the next call fail, the way a broken registry does.
        self.resolve_error: Exception | None = None
        self.download_error: Exception | None = None

    def publish(self, version: str, checksum: str | None = None) -> None:
        """Pretend a new training run wrote a new version."""
        self.version = version
        if checksum is not None:
            self.tags = {**self.tags, "model_sha256": checksum}

    def resolve(self, name: str, version: str | None, alias: str | None) -> VersionInfo:
        self.resolve_calls += 1
        if self.resolve_error is not None:
            raise self.resolve_error
        return VersionInfo(version=version or self.version, tags=dict(self.tags))

    def download(self, name: str, version: str, destination: Path) -> Path:
        self.download_calls += 1
        if self.download_error is not None:
            raise self.download_error
        target = Path(destination) / "model"
        shutil.copytree(self.model_dir, target)
        return target


class CountingLoader:
    """Wraps the real loader and remembers how often it ran.

    The checksum has to be checked before the pickle is opened, and this is
    how the tests prove that the order is right.
    """

    def __init__(self, loader) -> None:
        self._loader = loader
        self.calls = 0

    def __call__(self, model_dir: Path):
        self.calls += 1
        return self._loader(model_dir)
