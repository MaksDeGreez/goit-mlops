"""Build the committed snapshot of the California Housing dataset.

The platform must never download data at run time, so the dataset is fetched
once here and committed as a CSV file. Run this script only when the snapshot
has to be rebuilt (it needs network access):

    uv run --no-project --python 3.13 --with scikit-learn --with pandas \
        python final-project/scripts/fetch_dataset.py

The three "average" columns are rounded to six decimals. That keeps the file
under the 2 MB limit of the check-added-large-files hook and is far below the
precision the model needs. All other columns are written without any loss.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sklearn.datasets import fetch_california_housing

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CSV_PATH = DATA_DIR / "california_housing.csv"

COLUMNS = [
    "MedInc",
    "HouseAge",
    "AveRooms",
    "AveBedrms",
    "Population",
    "AveOccup",
    "Latitude",
    "Longitude",
    "MedHouseVal",
]

# Decimals per column. 4, 1, 2 and 5 are lossless for this dataset; only the
# three ratio columns lose anything, and only below the sixth decimal.
DECIMALS = {
    "MedInc": 4,
    "HouseAge": 1,
    "AveRooms": 6,
    "AveBedrms": 6,
    "Population": 1,
    "AveOccup": 6,
    "Latitude": 2,
    "Longitude": 2,
    "MedHouseVal": 5,
}


def main() -> None:
    frame = fetch_california_housing(as_frame=True).frame
    frame = frame[COLUMNS].round(DECIMALS)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(CSV_PATH, index=False)

    digest = hashlib.sha256(CSV_PATH.read_bytes()).hexdigest()
    print(f"rows: {len(frame)}")
    print(f"bytes: {CSV_PATH.stat().st_size}")
    print(f"sha256: {digest}")


if __name__ == "__main__":
    main()
