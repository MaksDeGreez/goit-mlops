"""Getting a model out of the MLflow registry and keeping it up to date.

The order of the steps is the point of this module:

1. ask the registry which version the alias points at (or take the pinned one);
2. download that version through the tracking server;
3. compute the checksum of the model file and compare it with the tag written
   by the training job, and with `MODEL_SHA256` when that is set;
4. only then deserialize.

Step 4 runs arbitrary code, because the model is a pickle. That is why step 3
comes first and why a mismatch stops everything: the service stays alive but
never becomes ready, so Kubernetes and Argo Rollouts see a pod that does not
work and no traffic reaches it.

Nothing here logs or counts anything. The app does that, which keeps this
module easy to test.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import mlflow
import mlflow.sklearn
from mlflow.tracking import MlflowClient

from inference.config import Settings
from inference.model_hash import model_file_sha256

MODEL_SHA256_TAG = "model_sha256"
GIT_SHA_TAG = "git_sha"
RUN_ID_TAG = "run_id"
DOWNLOAD_PREFIX = "inference-model-"


class ModelLoadError(RuntimeError):
    """A model could not be loaded.

    `reason` is a short label with a small set of values, because it becomes a
    Prometheus label. `details` are extra fields for the log line.
    """

    def __init__(self, reason: str, message: str, **details: object) -> None:
        super().__init__(message)
        self.reason = reason
        self.details = details


@dataclass(frozen=True)
class VersionInfo:
    """What the registry knows about one model version."""

    version: str
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LoadedModel:
    """A model that is in memory and whose checksum was checked."""

    model: Any
    version: str
    model_sha256: str
    git_sha: str | None
    run_id: str | None
    loaded_at: str
    local_dir: Path


class ModelSource(Protocol):
    """The part that talks to MLflow. The tests replace it with a fake."""

    def resolve(self, name: str, version: str | None, alias: str | None) -> VersionInfo: ...

    def download(self, name: str, version: str, destination: Path) -> Path: ...


class MlflowModelSource:
    """The real source: an MLflow tracking server with proxied artifacts."""

    def __init__(self, tracking_uri: str | None = None) -> None:
        if tracking_uri:
            mlflow.set_tracking_uri(tracking_uri)
        self._client = MlflowClient()

    def resolve(self, name: str, version: str | None, alias: str | None) -> VersionInfo:
        if version:
            model_version = self._client.get_model_version(name, version)
        else:
            model_version = self._client.get_model_version_by_alias(name, alias)
        return VersionInfo(version=str(model_version.version), tags=dict(model_version.tags))

    def download(self, name: str, version: str, destination: Path) -> Path:
        local_path = mlflow.artifacts.download_artifacts(
            artifact_uri=f"models:/{name}/{version}",
            dst_path=str(destination),
        )
        return Path(local_path)


def load_sklearn_model(model_dir: Path) -> Any:
    """Deserialize a downloaded MLflow model folder."""
    return mlflow.sklearn.load_model(str(model_dir))


class ModelStore:
    """Holds the model the service answers with, and can replace it."""

    def __init__(
        self,
        settings: Settings,
        source: ModelSource,
        loader: Callable[[Path], Any] = load_sklearn_model,
    ) -> None:
        self._settings = settings
        self._source = source
        self._loader = loader
        self._current: LoadedModel | None = None

    @property
    def current(self) -> LoadedModel | None:
        """The model in use, or None while nothing is loaded."""
        return self._current

    def refresh(self) -> LoadedModel | None:
        """Load the model when it is missing or out of date.

        Returns the new model, or None when there was nothing to do. Errors
        come out as `ModelLoadError`; the model already in use is then kept,
        so a broken registry does not take a running pod down.
        """
        wanted = self._resolve()
        if self._current is not None and self._current.version == wanted.version:
            return None
        return self._install(wanted)

    def _resolve(self) -> VersionInfo:
        settings = self._settings
        if settings.model_version and self._current is not None:
            # A pinned version never changes, so the registry is not asked
            # again once the model is loaded.
            return VersionInfo(version=settings.model_version)
        try:
            return self._source.resolve(
                settings.model_name, settings.model_version, settings.model_alias
            )
        except Exception as error:
            raise ModelLoadError("resolve_failed", f"cannot read the registry: {error}") from error

    def _install(self, wanted: VersionInfo) -> LoadedModel:
        destination = Path(tempfile.mkdtemp(prefix=DOWNLOAD_PREFIX))
        try:
            loaded = self._download_verify_load(wanted, destination)
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise

        previous = self._current
        self._current = loaded
        if previous is not None:
            shutil.rmtree(previous.local_dir, ignore_errors=True)
        return loaded

    def _download_verify_load(self, wanted: VersionInfo, destination: Path) -> LoadedModel:
        settings = self._settings
        try:
            model_dir = self._source.download(settings.model_name, wanted.version, destination)
        except Exception as error:
            raise ModelLoadError(
                "download_failed", f"cannot download version {wanted.version}: {error}"
            ) from error

        checksum = self._verify(wanted, model_dir)

        try:
            model = self._loader(model_dir)
        except Exception as error:
            raise ModelLoadError(
                "deserialize_failed", f"cannot load version {wanted.version}: {error}"
            ) from error

        return LoadedModel(
            model=model,
            version=wanted.version,
            model_sha256=checksum,
            git_sha=wanted.tags.get(GIT_SHA_TAG),
            run_id=wanted.tags.get(RUN_ID_TAG),
            loaded_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            local_dir=destination,
        )

    def _verify(self, wanted: VersionInfo, model_dir: Path) -> str:
        """Compare the checksum of the file that was just downloaded.

        This runs before the file is deserialized, so a swapped model never
        gets the chance to execute anything.
        """
        expected = wanted.tags.get(MODEL_SHA256_TAG)
        if not expected:
            raise ModelLoadError(
                "missing_checksum_tag",
                f"version {wanted.version} has no {MODEL_SHA256_TAG} tag",
                version=wanted.version,
            )

        try:
            actual = model_file_sha256(model_dir)
        except (OSError, ValueError) as error:
            raise ModelLoadError(
                "bad_artifact", f"version {wanted.version} is not a usable model: {error}"
            ) from error

        pinned = self._settings.model_sha256
        if actual != expected or (pinned and actual != pinned):
            raise ModelLoadError(
                "checksum_mismatch",
                f"the model file of version {wanted.version} is not the one that was trained",
                version=wanted.version,
                expected=expected,
                pinned=pinned,
                actual=actual,
            )
        return actual

    def close(self) -> None:
        """Remove the downloaded files. Called when the service stops."""
        if self._current is not None:
            shutil.rmtree(self._current.local_dir, ignore_errors=True)
            self._current = None
