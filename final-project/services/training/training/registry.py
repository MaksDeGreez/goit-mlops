"""Everything that talks to MLflow: logging, registering, tagging, aliases.

The rules of the project:

* every run creates a new model version;
* the new version gets the alias `staging` and the old stage name `Staging`;
* the version carries the tags the rest of the platform reads, above all
  `model_sha256`, which the inference service checks before it loads a model.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import mlflow
import mlflow.sklearn
import pandas as pd
import sklearn
from mlflow.models.model import ModelInfo
from mlflow.tracking import MlflowClient
from sklearn.pipeline import Pipeline

from training.model_hash import model_file_sha256

STAGING_ALIAS = "staging"
STAGING_STAGE = "Staging"
MODEL_ARTIFACT_NAME = "model"

# MLflow 3 writes scikit-learn models with skops by default. That format
# refuses to save a HistGradientBoostingRegressor or our own transformer
# without an explicit list of trusted types, so the classic cloudpickle format
# is used instead. The file is then called model.pkl. The risk cloudpickle
# brings is exactly what the model_sha256 tag is for: the inference service
# compares the checksum before it loads anything.
SERIALIZATION_FORMAT = "cloudpickle"

# The fitted pipeline contains our own steps, so the code of this package is
# stored next to the model. Loading it therefore needs no training image.
CODE_PATHS = [str(Path(__file__).resolve().parent)]


def pip_requirements() -> list[str]:
    """The three packages needed to load and run the model.

    They are listed by hand because MLflow otherwise reads the whole
    environment, which is slow and writes the test tools into the model.
    """
    return [
        f"mlflow=={mlflow.__version__}",
        f"scikit-learn=={sklearn.__version__}",
        f"pandas=={pd.__version__}",
    ]


def log_model(pipeline: Pipeline, input_example: pd.DataFrame | None = None) -> ModelInfo:
    """Store the fitted pipeline as an artifact of the active run."""
    return mlflow.sklearn.log_model(
        pipeline,
        name=MODEL_ARTIFACT_NAME,
        serialization_format=SERIALIZATION_FORMAT,
        code_paths=CODE_PATHS,
        input_example=input_example,
        pip_requirements=pip_requirements(),
    )


def register_version(model_uri: str, model_name: str) -> str:
    """Add the logged model to the registry and return the new version."""
    version = mlflow.register_model(model_uri, model_name)
    return str(version.version)


def download_version(model_name: str, version: str, destination: str | Path | None = None) -> Path:
    """Download a registered version and return the folder it is in.

    The download goes through the tracking server, so the job only needs HTTP
    access to it.
    """
    uri = f"models:/{model_name}/{version}"
    local_path = mlflow.artifacts.download_artifacts(
        artifact_uri=uri,
        dst_path=str(destination) if destination is not None else None,
    )
    return Path(local_path)


def model_version_sha256(
    model_name: str, version: str, destination: str | Path | None = None
) -> str:
    """Checksum of the model file of a version, as the registry stores it.

    The model is downloaded again on purpose: the hash then covers what every
    other service will really get, not what was in memory during training.
    """
    return model_file_sha256(download_version(model_name, version, destination))


def set_version_tags(
    client: MlflowClient, model_name: str, version: str, tags: dict[str, str]
) -> None:
    """Write the model version tags. Every value is stored as a string."""
    for key, value in tags.items():
        client.set_model_version_tag(model_name, version, key, str(value))


def promote_to_staging(client: MlflowClient, model_name: str, version: str) -> None:
    """Give the new version the alias `staging` and the stage `Staging`.

    Aliases are the way MLflow works today, and the services use them. The
    assignment describes the workflow with the old stage names, so the stage is
    set as well and the deprecation warning from that one call is hidden.
    """
    client.set_registered_model_alias(model_name, STAGING_ALIAS, version)

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=".*transition_model_version_stage.*",
            category=FutureWarning,
        )
        client.transition_model_version_stage(model_name, version, STAGING_STAGE)
