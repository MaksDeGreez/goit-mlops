"""Build the reference sample used by the drift monitor.

Drift is measured against data the model was trained on, so the sample is taken
from the training split only. The split here is exactly the one in
`services/training/training/preprocess.py` (same function, same test size, same
seed), so the rows in `reference.csv` are always training rows.

    uv run --no-project --python 3.13 --with scikit-learn --with pandas \
        python final-project/scripts/make_reference.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CSV_PATH = DATA_DIR / "california_housing.csv"
REFERENCE_PATH = DATA_DIR / "reference.csv"

TEST_SIZE = 0.2
SEED = 42
SAMPLE_ROWS = 2500


def main() -> None:
    frame = pd.read_csv(CSV_PATH)
    train, _ = train_test_split(frame, test_size=TEST_SIZE, random_state=SEED, shuffle=True)
    # sort_index keeps the file in the row order of the snapshot, which makes
    # the diff readable if the sample is ever rebuilt.
    sample = train.sample(n=SAMPLE_ROWS, random_state=SEED).sort_index()
    sample.to_csv(REFERENCE_PATH, index=False)

    print(f"train rows: {len(train)}")
    print(f"reference rows: {len(sample)}")
    print(f"bytes: {REFERENCE_PATH.stat().st_size}")


if __name__ == "__main__":
    main()
