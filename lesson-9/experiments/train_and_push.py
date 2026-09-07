"""Train a few models on the Iris dataset, track them in MLflow and push the
results to Prometheus PushGateway.

The script runs on a laptop, not in the cluster. Both services are reached
through "kubectl port-forward", so before running it you need:

    kubectl -n mlflow      port-forward svc/mlflow      5000:5000
    kubectl -n monitoring  port-forward svc/pushgateway 9091:9091

What it does:

1. loads the Iris dataset and splits it into a train and a test part;
2. trains a LogisticRegression once for every combination of C and max_iter;
3. logs the parameters, the metrics and the model itself to MLflow;
4. pushes accuracy and loss to PushGateway, labelled with the MLflow run id;
5. finds the run with the best accuracy and copies that model into best_model/.
"""

import os
import shutil
import sys
from pathlib import Path

import mlflow
from mlflow.exceptions import MlflowException
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
from sklearn.datasets import load_iris
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss
from sklearn.model_selection import train_test_split

# Addresses of the two services. Both can be overridden with environment
# variables, which is handy if you forward them to different local ports.
TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
PUSHGATEWAY = os.environ.get("PUSHGATEWAY_ADDRESS", "127.0.0.1:9091")

EXPERIMENT_NAME = "iris-logistic-regression"
PUSHGATEWAY_JOB = "mlflow_training"

# best_model/ sits next to experiments/, as the assignment asks.
BEST_MODEL_DIR = Path(__file__).resolve().parent.parent / "best_model"

# The parameter grid. Eight runs in total: four values of C, two of max_iter.
C_VALUES = [0.01, 0.1, 1.0, 10.0]
MAX_ITER_VALUES = [100, 500]

RANDOM_STATE = 42


def push_metrics(run_id, c, max_iter, accuracy, loss):
    """Send the metrics of one run to PushGateway.

    A normal Prometheus setup scrapes a service every few seconds, but this
    script finishes in a moment, so there would be nothing left to scrape.
    PushGateway is built for exactly this: the script pushes its numbers there
    and they stay until they are replaced.

    The run id goes into the grouping key, so every run keeps its own series
    and one run cannot overwrite another.
    """
    registry = CollectorRegistry()

    accuracy_gauge = Gauge(
        "mlflow_accuracy",
        "Accuracy of the model trained in this MLflow run",
        ["c", "max_iter"],
        registry=registry,
    )
    loss_gauge = Gauge(
        "mlflow_loss",
        "Log loss of the model trained in this MLflow run",
        ["c", "max_iter"],
        registry=registry,
    )

    labels = {"c": str(c), "max_iter": str(max_iter)}
    accuracy_gauge.labels(**labels).set(accuracy)
    loss_gauge.labels(**labels).set(loss)

    push_to_gateway(
        PUSHGATEWAY,
        job=PUSHGATEWAY_JOB,
        registry=registry,
        grouping_key={"run_id": run_id},
    )


def copy_best_model(best):
    """Download the model of the best run into best_model/."""
    if BEST_MODEL_DIR.exists():
        shutil.rmtree(BEST_MODEL_DIR)
    BEST_MODEL_DIR.mkdir(parents=True)

    # Downloading by model URI works no matter where MLflow decided to keep the
    # files. The download goes through the tracking server, which then talks to
    # MinIO, so only the MLflow port needs to be forwarded.
    mlflow.artifacts.download_artifacts(
        artifact_uri=best["model_uri"],
        dst_path=str(BEST_MODEL_DIR),
    )


def main():
    print(f"MLflow:      {TRACKING_URI}")
    print(f"PushGateway: {PUSHGATEWAY}")
    print()

    mlflow.set_tracking_uri(TRACKING_URI)
    try:
        mlflow.set_experiment(EXPERIMENT_NAME)
    except MlflowException as exc:
        print(f"Cannot reach MLflow at {TRACKING_URI}.")
        print("Is the port-forward running? Original error:")
        print(f"  {exc}")
        return 1

    data = load_iris()
    x_train, x_test, y_train, y_test = train_test_split(
        data.data,
        data.target,
        test_size=0.2,
        random_state=RANDOM_STATE,
        stratify=data.target,
    )

    results = []

    for c in C_VALUES:
        for max_iter in MAX_ITER_VALUES:
            with mlflow.start_run() as run:
                model = LogisticRegression(C=c, max_iter=max_iter)
                model.fit(x_train, y_train)

                predictions = model.predict(x_test)
                probabilities = model.predict_proba(x_test)

                accuracy = accuracy_score(y_test, predictions)
                loss = log_loss(y_test, probabilities, labels=list(range(len(data.target_names))))

                mlflow.log_params({"C": c, "max_iter": max_iter})
                mlflow.log_metrics({"accuracy": accuracy, "loss": loss})

                model_info = mlflow.sklearn.log_model(model, name="model")

                push_metrics(run.info.run_id, c, max_iter, accuracy, loss)

                results.append(
                    {
                        "run_id": run.info.run_id,
                        "c": c,
                        "max_iter": max_iter,
                        "accuracy": accuracy,
                        "loss": loss,
                        "model_uri": model_info.model_uri,
                    }
                )

                print(
                    f"C={c:<6} max_iter={max_iter:<5} "
                    f"accuracy={accuracy:.4f} loss={loss:.4f} run_id={run.info.run_id}"
                )

    # Highest accuracy wins. If two runs are equally accurate, the lower loss
    # breaks the tie, which is why loss is negated in the sort key.
    best = max(results, key=lambda r: (r["accuracy"], -r["loss"]))

    print()
    print("Best run:")
    print(f"  run_id   {best['run_id']}")
    print(f"  C        {best['c']}")
    print(f"  max_iter {best['max_iter']}")
    print(f"  accuracy {best['accuracy']:.4f}")
    print(f"  loss     {best['loss']:.4f}")

    copy_best_model(best)
    print(f"\nBest model copied to {BEST_MODEL_DIR}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
