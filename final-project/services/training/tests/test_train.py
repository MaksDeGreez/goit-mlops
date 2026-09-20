"""Tests for the pipeline and the metrics."""

from __future__ import annotations

import pytest

from training.data import FEATURE_COLUMNS, REPO_DATA_PATH, load_dataset
from training.preprocess import learn_clip_bounds, split_data, split_features_target
from training.train import TrainingParams, build_pipeline, evaluate, train_model

# A small sample and few iterations: these tests check the code, not the score.
FAST_PARAMS = TrainingParams(max_iter=30)


@pytest.fixture(scope="module")
def splits():
    frame = load_dataset(REPO_DATA_PATH, sample_rows=600)
    return split_data(frame)


def test_build_pipeline_has_the_expected_steps():
    pipeline = build_pipeline(FAST_PARAMS)

    assert list(pipeline.named_steps) == ["clip", "ratios", "scale", "model"]
    assert pipeline.named_steps["model"].max_iter == 30


def test_training_params_go_into_the_regressor():
    pipeline = build_pipeline(TrainingParams(max_iter=7, learning_rate=0.5, max_leaf_nodes=5))
    regressor = pipeline.named_steps["model"]

    assert (regressor.max_iter, regressor.learning_rate, regressor.max_leaf_nodes) == (7, 0.5, 5)


def test_train_model_predicts_one_value_per_row(splits):
    train, test = splits

    pipeline = train_model(train, FAST_PARAMS)
    features, _ = split_features_target(test)

    assert pipeline.predict(features).shape == (len(test),)


def test_train_model_learns_the_clip_bounds_on_the_train_split_only(splits):
    train, _ = splits

    pipeline = train_model(train, FAST_PARAMS)
    features, _ = split_features_target(train)

    assert pipeline.named_steps["clip"].bounds_ == learn_clip_bounds(features)


def test_the_pipeline_adds_the_ratio_features(splits):
    train, _ = splits
    features, _ = split_features_target(train)

    pipeline = train_model(train, FAST_PARAMS)
    transformed = pipeline[:-1].transform(features)

    assert transformed.shape[1] == len(FEATURE_COLUMNS) + 2


def test_the_same_data_and_params_give_the_same_metrics(splits):
    train, test = splits

    first = evaluate(train_model(train, FAST_PARAMS), test)
    second = evaluate(train_model(train, FAST_PARAMS), test)

    assert first == second


def test_evaluate_returns_the_three_metrics(splits):
    train, test = splits

    metrics = evaluate(train_model(train, FAST_PARAMS), test)

    assert sorted(metrics) == ["mae", "r2", "rmse"]
    assert all(isinstance(value, float) for value in metrics.values())
    assert metrics["rmse"] > 0
    assert metrics["mae"] <= metrics["rmse"]


def test_the_model_is_better_than_guessing_the_average(splits):
    train, test = splits

    metrics = evaluate(train_model(train, FAST_PARAMS), test)

    # r2 = 0 means "as good as always predicting the mean of the test set".
    assert metrics["r2"] > 0.4
