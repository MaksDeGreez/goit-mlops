"""Last step of the training pipeline: read the result of the training job.

The state before this one runs the training Job with
`arn:aws:states:::eks:runJob.sync` and `LogOptions.RetrieveLogs` turned on, so
its output carries the last lines the pod printed:

    {"job": {"logs": {"pods": {"<pod>": {"containers": {"<container>":
             {"log": "...\\n...\\n"}}}}}}}

The training job prints exactly one JSON line on stdout, the line with
`"event": "training_finished"`. This function looks for that line, writes the
metrics to CloudWatch as structured JSON and returns them, so the whole run can
be read from the output of the execution. If the line is not there the training
did not finish the way it should, and the function fails the execution.

Only the standard library is used, so the deployment package is a single file.
"""

import json
import os
from datetime import UTC, datetime

SERVICE = "log-metrics"
RESULT_EVENT = "training_finished"

# The numbers the training job reports. They are logged one by one so that a
# CloudWatch metric filter can pick them up later without any parsing rules.
METRIC_FIELDS = ("rmse", "mae", "r2")


class TrainingResultNotFoundError(Exception):
    """The training job did not print the line the pipeline needs."""


def log(level: str, event: str, **fields) -> None:
    """Print one JSON object per line, so CloudWatch can filter on the fields."""
    record = {
        "ts": datetime.now(tz=UTC).isoformat(),
        "level": level,
        "event": event,
        "service": SERVICE,
    }
    record.update(fields)
    print(json.dumps(record, default=str))


def iter_log_texts(node):
    """Yield every piece of log text inside the `logs` object.

    The shape is walked instead of being addressed by key, because the pod name
    and the container name are part of the path and the pod name is only known
    at run time. Walking also keeps the function working if AWS returns the log
    text directly instead of wrapping it in an object with a `log` key.
    """
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from iter_log_texts(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_log_texts(value)


def find_training_result(logs) -> dict:
    """Return the last `training_finished` object printed by the job."""
    found = None
    for text in iter_log_texts(logs):
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                # Ordinary log lines are not JSON. They are simply skipped.
                continue
            if isinstance(parsed, dict) and parsed.get("event") == RESULT_EVENT:
                # The last one wins: a retried pod prints the line again.
                found = parsed

    if found is None:
        raise TrainingResultNotFoundError(
            f"no '{RESULT_EVENT}' line in the logs of the training job. "
            "The job did not finish, or its logs were cut off."
        )
    return found


def lambda_handler(event, context):
    event = event or {}
    job = event.get("job")
    if not isinstance(job, dict):
        job = event
    logs = job.get("logs", {})

    result = find_training_result(logs)

    metrics = {name: result.get(name) for name in METRIC_FIELDS}
    log(
        "INFO",
        "training_metrics",
        job_name=event.get("job_name"),
        model=result.get("model"),
        version=result.get("version"),
        run_id=result.get("run_id"),
        git_sha=result.get("git_sha"),
        dataset_sha256=result.get("dataset_sha256"),
        model_sha256=result.get("model_sha256"),
        mlflow_tracking_uri=os.environ.get("MLFLOW_TRACKING_URI"),
        **metrics,
    )

    return {
        "event": "training_pipeline_finished",
        "job_name": event.get("job_name"),
        "image": event.get("image"),
        "git_sha": event.get("git_sha") or result.get("git_sha"),
        "training": result,
    }
