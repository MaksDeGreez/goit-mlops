"""The whole job, without a network: Loki is faked and nothing is pushed."""

from __future__ import annotations

import json

import pytest

from drift_monitor.drift import FEATURE_COLUMNS
from drift_monitor.run import main


def read_logs(capsys) -> list[dict]:
    """Every stdout line parsed as JSON, which is the log contract."""
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def events(logs: list[dict]) -> list[str]:
    return [line["event"] for line in logs]


def find(logs: list[dict], event: str) -> dict:
    return next(line for line in logs if line["event"] == event)


@pytest.fixture
def current_csv(shifted, tmp_path):
    path = tmp_path / "current.csv"
    shifted.to_csv(path, index=False)
    return str(path)


@pytest.fixture
def quiet_csv(same_as_reference, tmp_path):
    path = tmp_path / "quiet.csv"
    same_as_reference.to_csv(path, index=False)
    return str(path)


@pytest.fixture(autouse=True)
def no_pushgateway(monkeypatch):
    """Make sure a test can never reach a real gateway."""
    monkeypatch.delenv("PUSHGATEWAY_URL", raising=False)
    monkeypatch.setattr(
        "drift_monitor.run.push",
        lambda *a, **k: pytest.fail("the job must not push in the tests"),
    )


def test_a_run_from_a_csv_finds_the_drift(current_csv, capsys):
    code = main(["--current-csv", current_csv])
    logs = read_logs(capsys)

    assert code == 0
    assert events(logs) == [
        "started",
        "loaded_reference",
        "loaded_current",
        "drift_checked",
        "push_skipped",
    ]
    checked = find(logs, "drift_checked")
    assert checked["drifted_columns"] == 3
    assert checked["drifted_share"] == pytest.approx(0.375)
    assert checked["method"] == "psi"
    assert set(checked["scores"]) == set(FEATURE_COLUMNS)


def test_a_run_on_unchanged_data_reports_no_drift(quiet_csv, capsys):
    code = main(["--current-csv", quiet_csv])
    checked = find(read_logs(capsys), "drift_checked")

    assert code == 0
    assert checked["drifted_columns"] == 0
    assert checked["drifted_share"] == 0.0


def test_every_log_line_has_the_agreed_keys(quiet_csv, capsys):
    main(["--current-csv", quiet_csv])

    for line in read_logs(capsys):
        assert set(line) >= {"ts", "level", "event", "service"}
        assert line["service"] == "drift-monitor"
        assert line["ts"].endswith("Z")


def test_too_few_rows_stop_the_check_but_not_the_job(quiet_csv, capsys):
    code = main(["--current-csv", quiet_csv, "--min-samples", "5000"])
    logs = read_logs(capsys)

    assert code == 0
    assert "drift_checked" not in events(logs)
    warning = find(logs, "not_enough_samples")
    assert warning["level"] == "WARNING"
    assert warning["samples"] == 600
    assert warning["min_samples"] == 5000


def test_a_missing_file_gives_a_failure_line_and_exit_code_one(tmp_path, capsys):
    code = main(["--current-csv", str(tmp_path / "nothing.csv")])
    logs = read_logs(capsys)

    assert code == 1
    failure = find(logs, "failed")
    assert failure["level"] == "ERROR"
    assert failure["error_type"] == "FileNotFoundError"


def test_the_job_reads_loki_when_no_csv_is_given(loki_payload, monkeypatch, capsys):
    monkeypatch.setattr(
        "drift_monitor.run.query_range",
        lambda url, query, window_minutes, limit: loki_payload,
    )
    code = main(["--min-samples", "50"])
    loaded = find(read_logs(capsys), "loaded_current")

    assert code == 0
    assert loaded["source"] == "loki"
    assert loaded["lines"] == 100
    assert loaded["skipped_lines"] == 2
    assert loaded["samples"] == 98


def test_the_html_report_is_saved_when_a_directory_is_given(quiet_csv, tmp_path, capsys):
    reports = tmp_path / "reports"
    main(["--current-csv", quiet_csv, "--report-dir", str(reports)])
    saved = find(read_logs(capsys), "report_saved")

    assert list(reports.glob("drift-*.html"))
    assert saved["path"].endswith(".html")


def test_the_metrics_are_pushed_when_a_gateway_is_set(quiet_csv, monkeypatch, capsys):
    pushed = {}

    def fake_push(registry, url, job=None, **kwargs):
        pushed["url"] = url
        pushed["job"] = job
        pushed["share"] = registry.get_sample_value("data_drift_share")

    monkeypatch.setattr("drift_monitor.run.push", fake_push)
    code = main(["--current-csv", quiet_csv, "--pushgateway-url", "http://pushgateway:9091"])
    logs = read_logs(capsys)

    assert code == 0
    assert pushed == {"url": "http://pushgateway:9091", "job": "drift_monitor", "share": 0.0}
    assert find(logs, "pushed_metrics")["job"] == "drift_monitor"
