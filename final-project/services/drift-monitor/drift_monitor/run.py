"""Command line entry point of the drift job: `python -m drift_monitor`.

One run reads the predictions of the last hour from Loki, compares their
features with the reference sample and pushes the result to the PushGateway.
Finding drift is not an error: the job exits 0 and Prometheus decides what to
alert on. A non-zero exit code means the check could not be made.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

import pandas as pd

from drift_monitor.drift import (
    DRIFT_METHOD,
    FEATURE_COLUMNS,
    check_drift,
    default_reference_path,
    load_features,
)
from drift_monitor.logs import log
from drift_monitor.loki import events_to_frame, log_lines, prediction_events, query_range
from drift_monitor.metrics import PUSH_JOB, build_registry, push

DEFAULT_LOKI_URL = "http://loki-gateway.monitoring.svc.cluster.local"
DEFAULT_LOKI_QUERY = '{namespace="production", app="inference"} | json | event="prediction"'
DEFAULT_WINDOW_MINUTES = 60
DEFAULT_LIMIT = 5000
DEFAULT_MIN_SAMPLES = 100


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Read the settings. Every option also has an environment variable."""
    parser = argparse.ArgumentParser(description="Check the live features for data drift.")
    parser.add_argument(
        "--current-csv",
        help="read the live data from a CSV file instead of Loki",
    )
    parser.add_argument("--reference-csv", default=os.environ.get("REFERENCE_PATH"))
    parser.add_argument("--loki-url", default=os.environ.get("LOKI_URL", DEFAULT_LOKI_URL))
    parser.add_argument("--loki-query", default=os.environ.get("LOKI_QUERY", DEFAULT_LOKI_QUERY))
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=_int_from_env("WINDOW_MINUTES", DEFAULT_WINDOW_MINUTES),
    )
    parser.add_argument("--limit", type=int, default=_int_from_env("LOKI_LIMIT", DEFAULT_LIMIT))
    parser.add_argument(
        "--min-samples",
        type=int,
        default=_int_from_env("MIN_SAMPLES", DEFAULT_MIN_SAMPLES),
    )
    parser.add_argument(
        "--pushgateway-url",
        default=os.environ.get("PUSHGATEWAY_URL", ""),
        help="empty means do not push, which is handy for a local run",
    )
    parser.add_argument("--push-job", default=os.environ.get("PUSH_JOB", PUSH_JOB))
    parser.add_argument(
        "--report-dir",
        default=os.environ.get("REPORT_DIR"),
        help="save the Evidently HTML report here",
    )
    return parser.parse_args(argv)


def _int_from_env(name: str, fallback: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else fallback


def load_current(args: argparse.Namespace) -> pd.DataFrame:
    """The live data, either from a CSV file or from Loki."""
    if args.current_csv:
        frame = load_features(args.current_csv)
        log("loaded_current", source="csv", path=args.current_csv, samples=len(frame))
        return frame

    payload = query_range(args.loki_url, args.loki_query, args.window_minutes, args.limit)
    lines = log_lines(payload)
    events, skipped = prediction_events(lines)
    frame = events_to_frame(events, FEATURE_COLUMNS)
    log(
        "loaded_current",
        source="loki",
        window_minutes=args.window_minutes,
        lines=len(lines),
        skipped_lines=skipped,
        samples=len(frame),
    )
    return frame


def report_path(report_dir: str | None) -> Path | None:
    if not report_dir:
        return None
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    return Path(report_dir) / f"drift-{stamp}.html"


def push_metrics(args: argparse.Namespace, registry) -> None:
    if not args.pushgateway_url:
        log("push_skipped", reason="no pushgateway url")
        return
    push(registry, args.pushgateway_url, job=args.push_job)
    log("pushed_metrics", url=args.pushgateway_url, job=args.push_job)


def run(args: argparse.Namespace) -> int:
    reference_path = args.reference_csv or default_reference_path()
    reference = load_features(reference_path)
    log("loaded_reference", path=str(reference_path), rows=len(reference))

    current = load_current(args)

    if len(current) < args.min_samples:
        log(
            "not_enough_samples",
            level="WARNING",
            samples=len(current),
            min_samples=args.min_samples,
        )
        push_metrics(args, build_registry(None, samples=len(current)))
        return 0

    path = report_path(args.report_dir)
    result = check_drift(current, reference, report_path=path)
    if path is not None:
        log("report_saved", path=str(path))

    log(
        "drift_checked",
        method=DRIFT_METHOD,
        samples=result.samples,
        drifted_columns=result.drifted_columns,
        drifted_share=round(result.drifted_share, 4),
        threshold=result.threshold,
        drifted=result.drifted_column_names(),
        scores={column: round(score, 4) for column, score in sorted(result.scores.items())},
    )
    push_metrics(args, build_registry(result, samples=result.samples))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    log("started", min_samples=args.min_samples)
    try:
        return run(args)
    except Exception as error:
        # The message is enough for the log, the traceback is for a person and
        # goes to stderr so that stdout stays one JSON object per line.
        log("failed", level="ERROR", error=str(error), error_type=type(error).__name__)
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
