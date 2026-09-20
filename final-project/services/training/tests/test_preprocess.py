"""Tests for the preprocessing steps."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from training.data import EXPECTED_COLUMNS, FEATURE_COLUMNS, TARGET_COLUMN
from training.preprocess import (
    QuantileClipper,
    add_ratio_features,
    clip_outliers,
    learn_clip_bounds,
    split_data,
    split_features_target,
)


def make_frame(rows: int = 100) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    values = {column: rng.uniform(1.0, 10.0, rows) for column in EXPECTED_COLUMNS}
    return pd.DataFrame(values)


def test_add_ratio_features_computes_both_ratios():
    frame = pd.DataFrame({"AveRooms": [4.0], "AveBedrms": [1.0], "AveOccup": [2.0]})

    out = add_ratio_features(frame)

    assert out.loc[0, "BedrmsPerRoom"] == pytest.approx(0.25)
    assert out.loc[0, "RoomsPerPerson"] == pytest.approx(2.0)


def test_add_ratio_features_does_not_change_the_input():
    frame = pd.DataFrame({"AveRooms": [4.0], "AveBedrms": [1.0], "AveOccup": [2.0]})

    add_ratio_features(frame)

    assert list(frame.columns) == ["AveRooms", "AveBedrms", "AveOccup"]


def test_add_ratio_features_survives_a_zero():
    frame = pd.DataFrame({"AveRooms": [0.0], "AveBedrms": [1.0], "AveOccup": [0.0]})

    out = add_ratio_features(frame)

    assert out.loc[0, "BedrmsPerRoom"] == 0.0
    assert out.loc[0, "RoomsPerPerson"] == 0.0


def test_learn_clip_bounds_uses_the_quantiles():
    frame = pd.DataFrame({"AveRooms": [float(value) for value in range(101)]})

    bounds = learn_clip_bounds(frame, columns=("AveRooms",), lower_quantile=0.1, upper_quantile=0.9)

    assert bounds["AveRooms"] == pytest.approx((10.0, 90.0))


def test_learn_clip_bounds_skips_columns_that_are_not_there():
    frame = pd.DataFrame({"AveRooms": [1.0, 2.0]})

    bounds = learn_clip_bounds(frame, columns=("AveRooms", "NotThere"))

    assert list(bounds) == ["AveRooms"]


def test_learn_clip_bounds_rejects_impossible_quantiles():
    frame = pd.DataFrame({"AveRooms": [1.0, 2.0]})

    with pytest.raises(ValueError, match="quantiles"):
        learn_clip_bounds(frame, columns=("AveRooms",), lower_quantile=0.9, upper_quantile=0.1)


def test_clip_outliers_cuts_both_tails():
    frame = pd.DataFrame({"AveRooms": [0.0, 5.0, 100.0]})

    out = clip_outliers(frame, {"AveRooms": (1.0, 10.0)})

    assert out["AveRooms"].tolist() == [1.0, 5.0, 10.0]


def test_clip_outliers_keeps_other_columns():
    frame = pd.DataFrame({"AveRooms": [100.0], "MedInc": [3.0]})

    out = clip_outliers(frame, {"AveRooms": (1.0, 10.0)})

    assert out["MedInc"].tolist() == [3.0]


def test_quantile_clipper_learns_bounds_on_the_data_it_is_fitted_on():
    train = pd.DataFrame({"AveRooms": [float(value) for value in range(101)]})
    unseen = pd.DataFrame({"AveRooms": [-50.0, 500.0]})

    clipper = QuantileClipper(columns=("AveRooms",), lower_quantile=0.1, upper_quantile=0.9)
    clipper.fit(train)

    assert clipper.bounds_["AveRooms"] == pytest.approx((10.0, 90.0))
    # A value the clipper has never seen is cut to the bounds of the train set.
    assert clipper.transform(unseen)["AveRooms"].tolist() == [10.0, 90.0]


def test_quantile_clipper_can_be_cloned_by_sklearn():
    from sklearn.base import clone

    clipper = QuantileClipper(columns=("AveRooms",), lower_quantile=0.2, upper_quantile=0.8)

    copy = clone(clipper)

    assert copy.get_params() == clipper.get_params()


def test_split_data_uses_the_whole_frame_and_keeps_the_parts_apart():
    frame = make_frame(rows=100)

    train, test = split_data(frame, test_size=0.2)

    assert len(train) == 80
    assert len(test) == 20
    assert not set(train.index) & set(test.index)


def test_split_data_is_repeatable():
    frame = make_frame(rows=100)

    first_train, first_test = split_data(frame)
    second_train, second_test = split_data(frame)

    pd.testing.assert_frame_equal(first_train, second_train)
    pd.testing.assert_frame_equal(first_test, second_test)


def test_split_data_changes_with_another_seed():
    frame = make_frame(rows=100)

    train_a, _ = split_data(frame, seed=1)
    train_b, _ = split_data(frame, seed=2)

    assert list(train_a.index) != list(train_b.index)


def test_split_features_target_returns_the_eight_features():
    frame = make_frame(rows=10)

    features, target = split_features_target(frame)

    assert list(features.columns) == FEATURE_COLUMNS
    assert target.name == TARGET_COLUMN
    assert len(features) == len(target) == 10
