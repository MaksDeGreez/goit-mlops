"""The model itself: one scikit-learn pipeline and the metrics for it.

The pipeline holds the whole path from the eight raw features to the
prediction. That is on purpose: the inference service then only has to send the
raw features and cannot preprocess them in a slightly different way.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from training.preprocess import (
    RANDOM_SEED,
    QuantileClipper,
    add_ratio_features,
    split_features_target,
)


@dataclass(frozen=True)
class TrainingParams:
    """Hyper-parameters of the model. Everything has a default that works."""

    max_iter: int = 200
    learning_rate: float = 0.1
    max_leaf_nodes: int = 31
    min_samples_leaf: int = 20
    l2_regularization: float = 0.0
    random_state: int = RANDOM_SEED

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)


def build_pipeline(params: TrainingParams | None = None) -> Pipeline:
    """Clip the long tails, add the ratios, scale, then fit the regressor.

    The regressor is a histogram gradient boosting tree: it is fast on 20 000
    rows, needs no tuning to be decent and handles the skewed columns well.
    """
    params = params or TrainingParams()
    return Pipeline(
        steps=[
            ("clip", QuantileClipper()),
            ("ratios", FunctionTransformer(add_ratio_features)),
            ("scale", StandardScaler()),
            (
                "model",
                HistGradientBoostingRegressor(
                    max_iter=params.max_iter,
                    learning_rate=params.learning_rate,
                    max_leaf_nodes=params.max_leaf_nodes,
                    min_samples_leaf=params.min_samples_leaf,
                    l2_regularization=params.l2_regularization,
                    random_state=params.random_state,
                    early_stopping=False,
                ),
            ),
        ]
    )


def train_model(train_frame: pd.DataFrame, params: TrainingParams | None = None) -> Pipeline:
    """Fit the pipeline on the train split."""
    features, target = split_features_target(train_frame)
    pipeline = build_pipeline(params)
    pipeline.fit(features, target)
    return pipeline


def evaluate(pipeline: Pipeline, test_frame: pd.DataFrame) -> dict[str, float]:
    """Score the fitted pipeline on data it has not seen."""
    features, target = split_features_target(test_frame)
    predictions = pipeline.predict(features)
    return {
        "rmse": float(root_mean_squared_error(target, predictions)),
        "mae": float(mean_absolute_error(target, predictions)),
        "r2": float(r2_score(target, predictions)),
    }
