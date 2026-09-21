"""The metrics the job pushes."""

from __future__ import annotations

from prometheus_client import generate_latest

from drift_monitor.drift import DriftResult
from drift_monitor.metrics import build_registry

RESULT = DriftResult(
    samples=420,
    drifted_columns=2,
    drifted_share=0.25,
    scores={"MedInc": 1.5, "Latitude": 0.01},
    threshold=0.1,
)


def exposed(registry) -> str:
    return generate_latest(registry).decode()


def sample(registry, name: str, **labels: str) -> float:
    return registry.get_sample_value(name, labels or None)


def test_a_finished_check_pushes_every_metric():
    registry = build_registry(RESULT, samples=RESULT.samples)

    assert sample(registry, "data_drift_share") == 0.25
    assert sample(registry, "data_drift_columns") == 2
    assert sample(registry, "data_drift_samples") == 420
    assert sample(registry, "data_drift_last_run_timestamp_seconds") > 1_700_000_000


def test_every_column_gets_its_own_score():
    registry = build_registry(RESULT, samples=RESULT.samples)

    assert sample(registry, "data_drift_score", column="MedInc") == 1.5
    assert sample(registry, "data_drift_score", column="Latitude") == 0.01


def test_too_few_samples_push_only_the_count_and_the_time():
    registry = build_registry(None, samples=7)

    assert sample(registry, "data_drift_samples") == 7
    assert sample(registry, "data_drift_last_run_timestamp_seconds") is not None
    assert sample(registry, "data_drift_share") is None
    assert sample(registry, "data_drift_columns") is None


def test_the_exposed_text_has_a_help_line_for_every_metric():
    text = exposed(build_registry(RESULT, samples=RESULT.samples))

    for name in (
        "data_drift_share",
        "data_drift_columns",
        "data_drift_score",
        "data_drift_samples",
        "data_drift_last_run_timestamp_seconds",
    ):
        assert f"# HELP {name} " in text
    assert 'data_drift_score{column="MedInc"} 1.5' in text
