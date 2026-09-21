"""Checksum of the serialized model file inside an MLflow model folder.

Training writes this hash to the model version tag `model_sha256`. The
inference service downloads the same version, computes the hash again and
refuses to load the model if the two differ. That is why this module is copied
into the inference service **unchanged**, together with its test: two different
copies would look exactly like a tampered model file.

There is no mlflow import here on purpose. The module only needs to read a
small YAML file and hash one file, so it stays easy to copy and to test.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

MLMODEL_FILE = "MLmodel"
READ_CHUNK_BYTES = 1024 * 1024


def serialized_model_path(model_dir: str | Path) -> Path:
    """Path of the file that holds the model itself.

    MLflow writes the name into `flavors.sklearn.pickled_model` in the MLmodel
    file. The name depends on the format MLflow used (`model.pkl` for
    cloudpickle, `model.skops` for skops), so it is always read from there and
    never guessed.
    """
    directory = Path(model_dir)
    mlmodel_path = directory / MLMODEL_FILE
    if not mlmodel_path.is_file():
        raise FileNotFoundError(f"no {MLMODEL_FILE} file in {directory}")

    metadata = yaml.safe_load(mlmodel_path.read_text(encoding="utf-8")) or {}
    flavor = metadata.get("flavors", {}).get("sklearn", {})
    file_name = flavor.get("pickled_model")
    if not file_name:
        raise ValueError(f"{mlmodel_path} has no flavors.sklearn.pickled_model entry")

    model_file = directory / file_name
    if not model_file.is_file():
        raise FileNotFoundError(f"model file {file_name} is missing in {directory}")
    return model_file


def sha256_file(path: str | Path) -> str:
    """SHA256 of a file, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(READ_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def model_file_sha256(model_dir: str | Path) -> str:
    """SHA256 of the serialized model file in a downloaded model folder."""
    model_file = serialized_model_path(model_dir)
    if model_file.stat().st_size == 0:
        # A failed download can leave an empty or space-filled file behind, and
        # hashing it would give a valid looking but meaningless value.
        raise ValueError(f"model file {model_file} is empty")
    return sha256_file(model_file)
