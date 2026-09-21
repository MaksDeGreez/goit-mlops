"""The Prometheus metrics of the service.

Every metric that says something about the quality of the answers carries the
label `model_version`. During a canary rollout two versions run at the same
time, and the analysis that decides between "keep going" and "roll back" only
works if the two can be told apart.

The metrics live in a registry of their own instead of the global default one.
That way a second app in the same process (the tests build several) does not
try to register the same metric name twice.
"""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import (
    GC_COLLECTOR,
    PLATFORM_COLLECTOR,
    PROCESS_COLLECTOR,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
)

# The service answers in a few milliseconds, so the interesting range is small.
# The last buckets are there to make a real problem visible.
LATENCY_BUCKETS = (0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, float("inf"))
# The target is the median house value in units of $100,000, and the data is
# capped at 5.0.
PREDICTION_BUCKETS = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, float("inf"))

NO_MODEL = "none"


def status_class(status_code: int) -> str:
    """`2xx`, `4xx`, `5xx`. A refused request is not a broken service."""
    return f"{status_code // 100}xx"


@dataclass(frozen=True)
class Metrics:
    """All metrics of one app, together with the registry they live in."""

    registry: CollectorRegistry
    requests: Counter
    duration: Histogram
    predictions: Counter
    prediction_value: Histogram
    model_info: Gauge
    load_failures: Counter

    def observe_request(self, model_version: str | None, status_code: int, seconds: float) -> None:
        version = model_version or NO_MODEL
        self.requests.labels(model_version=version, status_class=status_class(status_code)).inc()
        self.duration.labels(model_version=version).observe(seconds)

    def observe_prediction(self, model_version: str, value: float) -> None:
        self.predictions.labels(model_version=model_version).inc()
        self.prediction_value.labels(model_version=model_version).observe(value)

    def set_model_info(self, model_name: str, model_version: str, model_sha256: str) -> None:
        # The old labels are dropped first, so after a hot swap the metric
        # describes one version only.
        self.model_info.clear()
        self.model_info.labels(
            model_name=model_name, model_version=model_version, model_sha256=model_sha256
        ).set(1)


def build_metrics() -> Metrics:
    """Create the registry and the metrics of one app."""
    registry = CollectorRegistry()
    # Memory, CPU and Python version of the process. They come from the
    # default registry, and the same collector can serve two registries.
    for collector in (PROCESS_COLLECTOR, PLATFORM_COLLECTOR, GC_COLLECTOR):
        registry.register(collector)

    return Metrics(
        registry=registry,
        requests=Counter(
            "inference_requests_total",
            "Requests answered, by model version and by class of the status code.",
            ["model_version", "status_class"],
            registry=registry,
        ),
        duration=Histogram(
            "inference_request_duration_seconds",
            "How long the service needed to answer a request.",
            ["model_version"],
            buckets=LATENCY_BUCKETS,
            registry=registry,
        ),
        predictions=Counter(
            "inference_predictions_total",
            "Predictions returned to a client.",
            ["model_version"],
            registry=registry,
        ),
        prediction_value=Histogram(
            "inference_prediction_value",
            "The predicted house value, in units of $100,000.",
            ["model_version"],
            buckets=PREDICTION_BUCKETS,
            registry=registry,
        ),
        model_info=Gauge(
            "inference_model_info",
            "Always 1. The labels say which model the pod serves.",
            ["model_name", "model_version", "model_sha256"],
            registry=registry,
        ),
        load_failures=Counter(
            "inference_model_load_failures_total",
            "Failed attempts to load a model, by reason.",
            ["reason"],
            registry=registry,
        ),
    )
