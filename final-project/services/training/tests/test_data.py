"""Tests for reading and checking the dataset snapshot."""

from __future__ import annotations

import pathlib

import pandas as pd
import pytest
from sklearn.model_selection import train_test_split

from training.data import (
    EXPECTED_COLUMNS,
    REPO_DATA_PATH,
    default_data_path,
    file_sha256,
    load_dataset,
    repo_file,
    validate_dataset,
)
from training.preprocess import RANDOM_SEED, TEST_SIZE

REFERENCE_PATH = REPO_DATA_PATH.parent / "reference.csv"

# Fixed vector, so the hashing itself is checked and not only compared with
# another call of the same function.
SAMPLE_BYTES = b"california-housing\n"
SAMPLE_SHA256 = "7ccb65fd60882b999475e4a9ea1c9636f8fd36c5efa1f465032f042f3bda136b"


def make_frame(rows: int = 4) -> pd.DataFrame:
    values = {column: [float(index + 1) for index in range(rows)] for column in EXPECTED_COLUMNS}
    return pd.DataFrame(values)


def test_file_sha256_matches_a_known_value(tmp_path):
    path = tmp_path / "sample.bin"
    path.write_bytes(SAMPLE_BYTES)

    assert file_sha256(path) == SAMPLE_SHA256


def test_file_sha256_reads_files_larger_than_one_chunk(tmp_path):
    path = tmp_path / "big.bin"
    path.write_bytes(SAMPLE_BYTES * 200_000)

    assert len(file_sha256(path)) == 64


def test_validate_dataset_accepts_a_correct_frame():
    validate_dataset(make_frame())


def test_validate_dataset_rejects_a_different_column_order():
    frame = make_frame()[list(reversed(EXPECTED_COLUMNS))]

    with pytest.raises(ValueError, match="unexpected columns"):
        validate_dataset(frame)


def test_validate_dataset_rejects_a_missing_column():
    frame = make_frame().drop(columns=["MedInc"])

    with pytest.raises(ValueError, match="unexpected columns"):
        validate_dataset(frame)


def test_validate_dataset_rejects_an_empty_frame():
    with pytest.raises(ValueError, match="empty"):
        validate_dataset(make_frame(rows=0))


def test_validate_dataset_rejects_text_values():
    frame = make_frame()
    frame["MedInc"] = "eight"

    with pytest.raises(ValueError, match="not numeric"):
        validate_dataset(frame)


def test_validate_dataset_rejects_missing_values():
    frame = make_frame()
    frame.loc[1, "Population"] = None

    with pytest.raises(ValueError, match="missing values"):
        validate_dataset(frame)


def test_load_dataset_reads_the_committed_snapshot():
    frame = load_dataset(REPO_DATA_PATH)

    assert list(frame.columns) == EXPECTED_COLUMNS
    assert len(frame) == 20640


def test_load_dataset_sample_is_smaller_and_always_the_same():
    first = load_dataset(REPO_DATA_PATH, sample_rows=500)
    second = load_dataset(REPO_DATA_PATH, sample_rows=500)

    assert len(first) == 500
    pd.testing.assert_frame_equal(first, second)


def test_load_dataset_ignores_a_sample_bigger_than_the_file(tmp_path):
    path = tmp_path / "small.csv"
    make_frame(rows=3).to_csv(path, index=False)

    assert len(load_dataset(path, sample_rows=100)) == 3


def test_load_dataset_reports_a_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_dataset(tmp_path / "nothing.csv")


def test_default_data_path_finds_the_snapshot_in_the_repository():
    assert default_data_path() == REPO_DATA_PATH


def test_repo_file_walks_four_folders_up():
    path = repo_file("/repo/final-project/services/training/training/data.py", "data")

    assert path == pathlib.Path("/repo/final-project/data")


def test_repo_file_survives_a_package_close_to_the_root():
    """Inside the image the package is /app/training, so there is no fourth
    parent. The path is then simply wrong and unused, but it must not raise:
    it is computed while the module is imported."""
    assert repo_file("/app/training/data.py", "data") == pathlib.Path("/data")


def test_reference_rows_come_from_the_train_split():
    """The drift reference must never contain test rows.

    `scripts/make_reference.py` uses the same split as the training code, so
    every row of reference.csv has to be in the train split.
    """
    frame = load_dataset(REPO_DATA_PATH)
    reference = pd.read_csv(REFERENCE_PATH)
    train, test = train_test_split(
        frame, test_size=TEST_SIZE, random_state=RANDOM_SEED, shuffle=True
    )

    train_rows = set(map(tuple, train.to_numpy().tolist()))
    test_rows = set(map(tuple, test.to_numpy().tolist()))
    reference_rows = set(map(tuple, reference.to_numpy().tolist()))

    assert list(reference.columns) == EXPECTED_COLUMNS
    assert len(reference) == 2500
    assert reference_rows <= train_rows
    assert not reference_rows & test_rows
