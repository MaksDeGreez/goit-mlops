"""First step of the training pipeline: check the input and build the job.

Step Functions calls this function with the input of the execution and the name
of the execution:

    {"input": {"image_tag": "...", "git_sha": "...", "params": {...}},
     "execution_name": "..."}

The answer holds everything the next state needs to start the Kubernetes Job:
the full image reference, a job name that is unique for this execution and the
command line arguments for the training script. A bad input raises an
exception, so the pipeline stops before a single pod is started.

The function only uses the standard library, so the deployment package is a
single file and there is nothing to build or to keep up to date.
"""

import json
import os
import re
from datetime import UTC, datetime

SERVICE = "validate-input"

# A Docker tag: letters, digits and the three separators, at most 128 characters.
IMAGE_TAG_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")

# A git commit, short or full. The training job also accepts "unknown", but the
# pipeline always knows the commit it was started for, so here it is required.
GIT_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,40}$")

# A safe value for a command line option: no spaces, no quotes, no shell characters.
PARAM_TEXT_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# The training options the pipeline is allowed to pass through, with the type
# each of them has to have. Everything else is rejected, so a typo in the CI
# input cannot end up as an unknown flag on the command line.
ALLOWED_PARAMS = {
    "experiment_name": str,
    "model_name": str,
    "sample_rows": int,
    "test_size": float,
    "seed": int,
    "max_iter": int,
    "learning_rate": float,
    "max_leaf_nodes": int,
    "min_samples_leaf": int,
    "l2_regularization": float,
}

# Kubernetes object names are at most 63 characters long.
MAX_JOB_NAME_LENGTH = 63


class InvalidInputError(ValueError):
    """The pipeline was started with an input it cannot use."""


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


def build_job_name(prefix: str, execution_name: str) -> str:
    """Turn the execution name into a name Kubernetes accepts.

    Step Functions gives every execution a unique name, so the job name is
    unique too and two runs can never collide.
    """
    slug = re.sub(r"[^a-z0-9-]", "-", execution_name.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        raise InvalidInputError("execution_name has no character a job name could use")

    name = f"{prefix}-{slug}"[:MAX_JOB_NAME_LENGTH].strip("-")
    if not name:
        raise InvalidInputError("the job name prefix is empty")
    return name


def _check_text(name: str, value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidInputError(f"{name} is missing or is not a string")
    return value.strip()


def build_args(params) -> list[str]:
    """Turn the optional training parameters into command line arguments."""
    if params is None:
        return []
    if not isinstance(params, dict):
        raise InvalidInputError("params must be an object")

    args: list[str] = []
    for key in sorted(params):
        if key not in ALLOWED_PARAMS:
            allowed = ", ".join(sorted(ALLOWED_PARAMS))
            raise InvalidInputError(f"unknown training parameter '{key}'. Allowed: {allowed}")

        value = params[key]
        expected = ALLOWED_PARAMS[key]

        # bool is a subclass of int in Python, but no option here takes a flag.
        if isinstance(value, bool):
            raise InvalidInputError(f"parameter '{key}' must be a {expected.__name__}")

        if expected is str:
            text = _check_text(f"parameter '{key}'", value)
            if not PARAM_TEXT_PATTERN.match(text):
                raise InvalidInputError(f"parameter '{key}' has characters that are not allowed")
        else:
            if isinstance(value, str):
                raise InvalidInputError(f"parameter '{key}' must be a {expected.__name__}")
            try:
                text = str(expected(value))
            except (TypeError, ValueError) as error:
                raise InvalidInputError(
                    f"parameter '{key}' must be a {expected.__name__}"
                ) from error

        args.extend([f"--{key.replace('_', '-')}", text])

    return args


def lambda_handler(event, context):
    repository = os.environ.get("TRAINING_IMAGE_REPOSITORY", "").strip()
    if not repository:
        raise InvalidInputError("TRAINING_IMAGE_REPOSITORY is not set on the function")

    prefix = os.environ.get("JOB_NAME_PREFIX", "training").strip() or "training"

    event = event or {}
    payload = event.get("input")
    if payload is None:
        # Makes the function easy to call by hand: a plain input works too.
        payload = {k: v for k, v in event.items() if k != "execution_name"}
    if not isinstance(payload, dict):
        raise InvalidInputError("the pipeline input must be an object")

    execution_name = event.get("execution_name") or getattr(context, "aws_request_id", "")
    execution_name = _check_text("execution_name", execution_name)

    image_tag = _check_text("image_tag", payload.get("image_tag"))
    if not IMAGE_TAG_PATTERN.match(image_tag):
        raise InvalidInputError(f"image_tag '{image_tag}' is not a valid container tag")

    git_sha = _check_text("git_sha", payload.get("git_sha"))
    if not GIT_SHA_PATTERN.match(git_sha):
        raise InvalidInputError("git_sha must be a commit hash of 7 to 40 hex characters")
    git_sha = git_sha.lower()

    args = build_args(payload.get("params"))
    job_name = build_job_name(prefix, execution_name)

    result = {
        "image": f"{repository}:{image_tag}",
        "image_tag": image_tag,
        "git_sha": git_sha,
        "job_name": job_name,
        "args": args,
        "execution_name": execution_name,
    }

    log("INFO", "input_validated", **result)
    return result
