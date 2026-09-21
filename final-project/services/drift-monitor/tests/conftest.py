"""Test data. Nothing here touches the network."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from drift_monitor.drift import FEATURE_COLUMNS, REPO_REFERENCE_PATH

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LOKI_ANSWER = FIXTURES / "loki_query_range.json"


@pytest.fixture
def loki_payload() -> dict:
    """A real shaped query_range answer: two streams plus two useless lines."""
    return json.loads(LOKI_ANSWER.read_text())


@pytest.fixture(scope="session")
def reference() -> pd.DataFrame:
    """The committed reference sample, features only."""
    return pd.read_csv(REPO_REFERENCE_PATH)[FEATURE_COLUMNS]


@pytest.fixture(scope="session")
def same_as_reference(reference: pd.DataFrame) -> pd.DataFrame:
    """Live data drawn from the reference itself, so there is no drift."""
    return reference.sample(n=600, random_state=3).reset_index(drop=True)


@pytest.fixture(scope="session")
def shifted(same_as_reference: pd.DataFrame) -> pd.DataFrame:
    """The same rows with three features moved, the way a broken client looks."""
    frame = same_as_reference.copy()
    frame["MedInc"] = frame["MedInc"] * 3.0
    frame["AveRooms"] = frame["AveRooms"] + 6.0
    rng = np.random.default_rng(11)
    frame["Population"] = rng.uniform(8000, 20000, size=len(frame))
    return frame
