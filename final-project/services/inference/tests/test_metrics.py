"""Tests for the Prometheus metrics."""

from __future__ import annotations

import pytest
from prometheus_client import generate_latest

from inference.metrics import build_metrics, status_class


@pytest.fixture
def metrics():
    return build_metrics()


def text(metrics) -> str:
    return generate_latest(metrics.registry).decode()


@pytest.mark.parametrize(
    ("status", "expected"),
    [(200, "2xx"), (400, "4xx"), (429, "4xx"), (500, "5xx"), (503, "5xx")],
)
def test_a_refused_request_is_not_counted_as_a_broken_service(status, expected):
    assert status_class(status) == expected


def test_two_apps_in_one_process_do_not_share_a_registry():
    """The tests build several apps, and metric names must not clash."""
    first, second = build_metrics(), build_metrics()

    assert first.registry is not second.registry


def test_a_request_is_counted_with_the_version_and_the_status_class(metrics):
    metrics.observe_request("3", 200, 0.004)
    metrics.observe_request("3", 400, 0.001)

    body = text(metrics)
    assert 'inference_requests_total{model_version="3",status_class="2xx"} 1.0' in body
    assert 'inference_requests_total{model_version="3",status_class="4xx"} 1.0' in body
    assert 'inference_request_duration_seconds_count{model_version="3"} 2.0' in body


def test_a_request_answered_before_the_model_is_loaded_is_still_counted(metrics):
    metrics.observe_request(None, 503, 0.001)

    assert 'model_version="none",status_class="5xx"' in text(metrics)


def test_a_prediction_is_counted_and_its_value_is_kept(metrics):
    metrics.observe_prediction("3", 2.5)

    body = text(metrics)
    assert 'inference_predictions_total{model_version="3"} 1.0' in body
    assert 'inference_prediction_value_sum{model_version="3"} 2.5' in body


def test_the_model_info_gauge_describes_only_the_model_in_use(metrics):
    metrics.set_model_info("california-housing", "1", "a" * 64)
    metrics.set_model_info("california-housing", "2", "b" * 64)

    body = text(metrics)
    assert 'model_version="1"' not in body
    assert 'model_version="2"' in body
    assert body.count("inference_model_info{") == 1


def test_a_failed_load_is_counted_by_reason(metrics):
    metrics.load_failures.labels(reason="checksum_mismatch").inc()

    assert 'inference_model_load_failures_total{reason="checksum_mismatch"} 1.0' in text(metrics)


def test_the_standard_collectors_are_exposed_as_well(metrics):
    """The CPU and memory of the process come from these collectors too.

    Only `python_info` is checked here: the memory numbers are read from
    /proc, so they exist in the container but not on a developer's Mac.
    """
    assert "python_info" in text(metrics)
