"""Command line entry point of the training job: `python -m training.run`.

One run reads the dataset snapshot, trains the pipeline, scores it on the test
split, registers a new model version, tags it and moves the alias `staging` to
it. The last line on stdout is a single JSON object, which the Lambda of the
Step Functions pipeline reads.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import mlflow
from mlflow.tracking import MlflowClient

from training.data import default_data_path, file_sha256, load_dataset
from training.preprocess import RANDOM_SEED, TEST_SIZE, split_data, split_features_target
from training.registry import (
    STAGING_ALIAS,
    log_model,
    model_version_sha256,
    promote_to_staging,
    register_version,
    set_version_tags,
)
from training.train import TrainingParams, evaluate, train_model

DEFAULT_MODEL_NAME = "california-housing"
DEFAULT_EXPERIMENT_NAME = "california-housing"
UNKNOWN_GIT_SHA = "unknown"
INPUT_EXAMPLE_ROWS = 5

log = logging.getLogger("training")


def resolve_git_sha(value: str | None) -> str:
    """The commit the code came from: from the environment, else from git."""
    if value:
        return value
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).resolve().parent,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        # There is no git inside the image. The CI pipeline passes GIT_SHA.
        return UNKNOWN_GIT_SHA
    return result.stdout.strip() or UNKNOWN_GIT_SHA


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Read the settings. Every option also has an environment variable."""
    parser = argparse.ArgumentParser(description="Train the California Housing model.")
    parser.add_argument("--tracking-uri", default=os.environ.get("MLFLOW_TRACKING_URI"))
    parser.add_argument("--model-name", default=os.environ.get("MODEL_NAME", DEFAULT_MODEL_NAME))
    parser.add_argument(
        "--experiment-name",
        default=os.environ.get("EXPERIMENT_NAME", DEFAULT_EXPERIMENT_NAME),
    )
    parser.add_argument("--data-path", default=os.environ.get("DATA_PATH"))
    parser.add_argument("--git-sha", default=os.environ.get("GIT_SHA"))
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=_int_from_env("SAMPLE_ROWS"),
        help="train on this many rows instead of the whole file",
    )
    parser.add_argument("--test-size", type=float, default=TEST_SIZE)
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    parser.add_argument("--max-iter", type=int, default=TrainingParams.max_iter)
    parser.add_argument("--learning-rate", type=float, default=TrainingParams.learning_rate)
    parser.add_argument("--max-leaf-nodes", type=int, default=TrainingParams.max_leaf_nodes)
    parser.add_argument("--min-samples-leaf", type=int, default=TrainingParams.min_samples_leaf)
    parser.add_argument("--l2-regularization", type=float, default=TrainingParams.l2_regularization)
    return parser.parse_args(argv)


def _int_from_env(name: str) -> int | None:
    value = os.environ.get(name)
    return int(value) if value else None


def run_training(args: argparse.Namespace) -> dict[str, object]:
    """One full training run. Returns the fields of the final JSON line."""
    data_path = Path(args.data_path) if args.data_path else default_data_path()
    git_sha = resolve_git_sha(args.git_sha)
    dataset_sha256 = file_sha256(data_path)
    log.info("data %s (sha256 %s)", data_path, dataset_sha256)

    frame = load_dataset(data_path, sample_rows=args.sample_rows, seed=args.seed)
    train_frame, test_frame = split_data(frame, test_size=args.test_size, seed=args.seed)
    log.info("rows: %d train, %d test", len(train_frame), len(test_frame))

    params = TrainingParams(
        max_iter=args.max_iter,
        learning_rate=args.learning_rate,
        max_leaf_nodes=args.max_leaf_nodes,
        min_samples_leaf=args.min_samples_leaf,
        l2_regularization=args.l2_regularization,
        random_state=args.seed,
    )

    if args.tracking_uri:
        mlflow.set_tracking_uri(args.tracking_uri)
    mlflow.set_experiment(args.experiment_name)

    with mlflow.start_run() as run:
        run_id = run.info.run_id
        mlflow.log_params(
            {
                **params.as_dict(),
                "test_size": args.test_size,
                "seed": args.seed,
                "rows": len(frame),
                "train_rows": len(train_frame),
                "test_rows": len(test_frame),
                "git_sha": git_sha,
                "dataset_sha256": dataset_sha256,
            }
        )
        # The same two values as tags as well: tags can be searched in the UI.
        mlflow.set_tags({"git_sha": git_sha, "dataset_sha256": dataset_sha256})

        pipeline = train_model(train_frame, params)
        metrics = evaluate(pipeline, test_frame)
        mlflow.log_metrics(metrics)
        log.info("metrics: %s", metrics)

        features, _ = split_features_target(train_frame)
        model_info = log_model(pipeline, input_example=features.head(INPUT_EXAMPLE_ROWS))

    version = register_version(model_info.model_uri, args.model_name)
    model_sha256 = model_version_sha256(args.model_name, version)
    log.info("registered %s version %s (sha256 %s)", args.model_name, version, model_sha256)

    client = MlflowClient()
    set_version_tags(
        client,
        args.model_name,
        version,
        {
            "git_sha": git_sha,
            "dataset_sha256": dataset_sha256,
            "model_sha256": model_sha256,
            "rmse": f"{metrics['rmse']:.6f}",
            "mae": f"{metrics['mae']:.6f}",
            "r2": f"{metrics['r2']:.6f}",
            "run_id": run_id,
        },
    )
    promote_to_staging(client, args.model_name, version)
    log.info("version %s now has the alias %s", version, STAGING_ALIAS)

    return {
        "event": "training_finished",
        "model": args.model_name,
        "version": version,
        "run_id": run_id,
        "rmse": metrics["rmse"],
        "mae": metrics["mae"],
        "r2": metrics["r2"],
        "git_sha": git_sha,
        "dataset_sha256": dataset_sha256,
        "model_sha256": model_sha256,
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    try:
        result = run_training(parse_args(argv))
    except Exception:
        # The pipeline only needs the non-zero exit code, a person needs the
        # traceback, so it goes to stderr and stdout stays machine readable.
        log.exception("training failed")
        return 1

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
