"""Tests for the model checksum helper.

This file is copied into the inference service together with
`training/model_hash.py`. Both copies must stay identical, because the two
services compare the hashes they compute.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from inference.model_hash import model_file_sha256, serialized_model_path, sha256_file

# Fixed test vector: these exact bytes always have this hash.
MODEL_BYTES = b"model bytes for the hash test\n"
MODEL_SHA256 = "0fca97bf0e568b88798a87b78093b02599e3a5deb1a90041f32ae1514729459d"

MLMODEL_TEMPLATE = """\
flavors:
  python_function:
    loader_module: mlflow.sklearn
    model_path: {file_name}
  sklearn:
    pickled_model: {file_name}
    serialization_format: cloudpickle
    sklearn_version: 1.9.1
mlflow_version: 3.16.1
"""


def make_model_dir(root: Path, file_name: str = "model.pkl", content: bytes = MODEL_BYTES) -> Path:
    model_dir = root / "model"
    model_dir.mkdir()
    (model_dir / "MLmodel").write_text(MLMODEL_TEMPLATE.format(file_name=file_name))
    (model_dir / file_name).write_bytes(content)
    return model_dir


def test_sha256_file_matches_a_known_value(tmp_path):
    path = tmp_path / "model.pkl"
    path.write_bytes(MODEL_BYTES)

    assert sha256_file(path) == MODEL_SHA256


def test_model_file_sha256_hashes_the_file_named_in_the_mlmodel_file(tmp_path):
    model_dir = make_model_dir(tmp_path)

    assert model_file_sha256(model_dir) == MODEL_SHA256


def test_model_file_sha256_follows_the_name_in_the_mlmodel_file(tmp_path):
    """MLflow 3 names the file model.skops when it uses the skops format."""
    model_dir = make_model_dir(tmp_path, file_name="model.skops")

    assert serialized_model_path(model_dir).name == "model.skops"
    assert model_file_sha256(model_dir) == MODEL_SHA256


def test_model_file_sha256_ignores_the_other_files_in_the_folder(tmp_path):
    model_dir = make_model_dir(tmp_path)
    (model_dir / "requirements.txt").write_text("mlflow\n")
    (model_dir / "conda.yaml").write_text("name: test\n")

    assert model_file_sha256(model_dir) == MODEL_SHA256


def test_model_file_sha256_changes_when_one_byte_changes(tmp_path):
    model_dir = make_model_dir(tmp_path, content=MODEL_BYTES.replace(b"model", b"Model"))

    assert model_file_sha256(model_dir) != MODEL_SHA256


def test_model_file_sha256_rejects_an_empty_model_file(tmp_path):
    model_dir = make_model_dir(tmp_path, content=b"")

    with pytest.raises(ValueError, match="empty"):
        model_file_sha256(model_dir)


def test_serialized_model_path_reports_a_missing_mlmodel_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="MLmodel"):
        serialized_model_path(tmp_path)


def test_serialized_model_path_reports_an_mlmodel_file_without_the_entry(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "MLmodel").write_text("flavors:\n  python_function: {}\n")

    with pytest.raises(ValueError, match="pickled_model"):
        serialized_model_path(model_dir)


def test_serialized_model_path_reports_a_missing_model_file(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "MLmodel").write_text(MLMODEL_TEMPLATE.format(file_name="model.pkl"))

    with pytest.raises(FileNotFoundError, match="model.pkl"):
        serialized_model_path(model_dir)
