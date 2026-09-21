"""The Prometheus metrics the job pushes to the PushGateway.

A CronJob is gone before Prometheus can scrape it, so it pushes instead. Every
run replaces the metrics of the job `drift_monitor`, so the gateway always
shows the last check.
"""

from __future__ import annotations

import time

from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

from drift_monitor.drift import DriftResult

PUSH_JOB = "drift_monitor"


def build_registry(result: DriftResult | None, samples: int) -> CollectorRegistry:
    """The metrics of one run.

    With too few samples `result` is None: the number of samples and the time
    of the run are still pushed, so a dashboard can tell "no traffic" apart
    from "the job is not running at all".
    """
    registry = CollectorRegistry()

    Gauge(
        "data_drift_samples",
        "Rows of live data the last drift check used",
        registry=registry,
    ).set(samples)
    Gauge(
        "data_drift_last_run_timestamp_seconds",
        "Unix time of the last drift check",
        registry=registry,
    ).set(time.time())

    if result is None:
        return registry

    Gauge(
        "data_drift_share",
        "Share of feature columns that drifted, 0 to 1",
        registry=registry,
    ).set(result.drifted_share)
    Gauge(
        "data_drift_columns",
        "Number of feature columns that drifted",
        registry=registry,
    ).set(result.drifted_columns)

    per_column = Gauge(
        "data_drift_score",
        "PSI distance between the live data and the reference, per column",
        ["column"],
        registry=registry,
    )
    for column, score in result.scores.items():
        per_column.labels(column=column).set(score)

    return registry


def push(registry: CollectorRegistry, url: str, job: str = PUSH_JOB, timeout: float = 10.0) -> None:
    push_to_gateway(url.rstrip("/"), job=job, registry=registry, timeout=timeout)
