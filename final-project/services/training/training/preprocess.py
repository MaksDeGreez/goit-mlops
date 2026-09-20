"""Preprocessing steps for the California Housing model.

The functions here are small and pure, so they are easy to test. The clipper is
a normal scikit-learn transformer: it learns its bounds in `fit`, which means
the pipeline learns them on the train split only and the test split stays
untouched.

This module is logged together with the model (`code_paths`), so the inference
service can load the pipeline without having the training code installed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.model_selection import train_test_split

from training.data import FEATURE_COLUMNS, TARGET_COLUMN

RANDOM_SEED = 42
TEST_SIZE = 0.2

# Columns with a long tail. A block group with 140 rooms per household is a
# small area with a hotel or a barracks in it, not a normal home.
CLIP_COLUMNS = ("AveRooms", "AveBedrms", "AveOccup", "Population")
LOWER_QUANTILE = 0.01
UPPER_QUANTILE = 0.99

Bounds = dict[str, tuple[float, float]]


def add_ratio_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Add two ratios that the raw columns only hide.

    `BedrmsPerRoom` says how much of a home is bedrooms, which separates small
    flats from large houses. `RoomsPerPerson` says how crowded a home is.
    """
    out = frame.copy()
    rooms = out["AveRooms"].replace(0.0, np.nan)
    people = out["AveOccup"].replace(0.0, np.nan)
    out["BedrmsPerRoom"] = (out["AveBedrms"] / rooms).fillna(0.0)
    out["RoomsPerPerson"] = (out["AveRooms"] / people).fillna(0.0)
    return out


def learn_clip_bounds(
    frame: pd.DataFrame,
    columns: tuple[str, ...] = CLIP_COLUMNS,
    lower_quantile: float = LOWER_QUANTILE,
    upper_quantile: float = UPPER_QUANTILE,
) -> Bounds:
    """Lower and upper bound per column, taken from quantiles."""
    if not 0.0 <= lower_quantile < upper_quantile <= 1.0:
        raise ValueError("quantiles must be between 0 and 1 and lower must be the smaller one")

    return {
        column: (
            float(frame[column].quantile(lower_quantile)),
            float(frame[column].quantile(upper_quantile)),
        )
        for column in columns
        if column in frame.columns
    }


def clip_outliers(frame: pd.DataFrame, bounds: Bounds) -> pd.DataFrame:
    """Cut every column in `bounds` to the given range."""
    out = frame.copy()
    for column, (lower, upper) in bounds.items():
        if column in out.columns:
            out[column] = out[column].clip(lower, upper)
    return out


class QuantileClipper(BaseEstimator, TransformerMixin):
    """Clip long tails to the quantile range learned on the training data."""

    def __init__(
        self,
        columns: tuple[str, ...] = CLIP_COLUMNS,
        lower_quantile: float = LOWER_QUANTILE,
        upper_quantile: float = UPPER_QUANTILE,
    ) -> None:
        self.columns = columns
        self.lower_quantile = lower_quantile
        self.upper_quantile = upper_quantile

    def fit(self, X: pd.DataFrame, y=None) -> QuantileClipper:
        self.bounds_ = learn_clip_bounds(X, self.columns, self.lower_quantile, self.upper_quantile)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        return clip_outliers(X, self.bounds_)


def split_data(
    frame: pd.DataFrame,
    test_size: float = TEST_SIZE,
    seed: int = RANDOM_SEED,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split into train and test with a fixed seed, so runs are repeatable."""
    return train_test_split(frame, test_size=test_size, random_state=seed, shuffle=True)


def split_features_target(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Separate the eight features from the target column."""
    return frame[FEATURE_COLUMNS].copy(), frame[TARGET_COLUMN].copy()
