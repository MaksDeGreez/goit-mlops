"""Reading and checking the dataset snapshot.

The snapshot is a CSV file committed in `final-project/data/`. Nothing is
downloaded at run time, so a training run always uses data that is in git.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

FEATURE_COLUMNS = [
    "MedInc",
    "HouseAge",
    "AveRooms",
    "AveBedrms",
    "Population",
    "AveOccup",
    "Latitude",
    "Longitude",
]
TARGET_COLUMN = "MedHouseVal"
EXPECTED_COLUMNS = [*FEATURE_COLUMNS, TARGET_COLUMN]

# The image is built with `final-project/` as the build context and everything
# is copied to /app, so in a container the snapshot is here.
CONTAINER_DATA_PATH = Path("/app/data/california_housing.csv")

READ_CHUNK_BYTES = 1024 * 1024


def repo_file(module_file: str | Path, *parts: str) -> Path:
    """A file in `final-project/`, seen from a module of this service.

    `services/training/training/data.py` is four folders below
    `final-project/`. The `.parent` chain is used instead of `.parents[3]`
    because it stops at "/" instead of raising: inside the image the package
    sits at `/app/training/`, where a fourth parent does not exist.
    """
    root = Path(module_file).resolve().parent.parent.parent.parent
    return root.joinpath(*parts)


# Where the same file is when the code runs from a git checkout.
REPO_DATA_PATH = repo_file(__file__, "data", "california_housing.csv")


def default_data_path() -> Path:
    """Where to look for the snapshot when DATA_PATH is not set."""
    for candidate in (CONTAINER_DATA_PATH, REPO_DATA_PATH):
        if candidate.is_file():
            return candidate
    # Nothing found: return the container path so the error message shows the
    # place the job normally reads from.
    return CONTAINER_DATA_PATH


def file_sha256(path: str | Path) -> str:
    """SHA256 of a file, read in chunks so a large file fits in memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(READ_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def validate_dataset(frame: pd.DataFrame) -> None:
    """Fail early if the snapshot is not what the training code expects."""
    columns = list(frame.columns)
    if columns != EXPECTED_COLUMNS:
        raise ValueError(f"unexpected columns: expected {EXPECTED_COLUMNS}, got {columns}")
    if frame.empty:
        raise ValueError("the dataset is empty")

    not_numeric = [
        column
        for column in EXPECTED_COLUMNS
        if not pd.api.types.is_numeric_dtype(frame[column].dtype)
    ]
    if not_numeric:
        raise ValueError(f"these columns are not numeric: {not_numeric}")

    with_nan = [column for column in EXPECTED_COLUMNS if frame[column].isna().any()]
    if with_nan:
        raise ValueError(f"these columns contain missing values: {with_nan}")


def load_dataset(
    path: str | Path | None = None,
    sample_rows: int | None = None,
    seed: int = 42,
) -> pd.DataFrame:
    """Read the snapshot, check it and optionally take a smaller sample.

    `sample_rows` is used by the tests and by smoke runs. The sample uses a
    fixed seed, so the same number of rows always gives the same rows.
    """
    csv_path = Path(path) if path is not None else default_data_path()
    if not csv_path.is_file():
        raise FileNotFoundError(f"dataset not found: {csv_path}")

    frame = pd.read_csv(csv_path)
    validate_dataset(frame)

    if sample_rows is not None and sample_rows < len(frame):
        if sample_rows <= 0:
            raise ValueError("sample_rows must be greater than zero")
        frame = frame.sample(n=sample_rows, random_state=seed).sort_index()

    return frame.reset_index(drop=True)
