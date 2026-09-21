"""Reading prediction events out of a Loki answer."""

from __future__ import annotations

import pandas as pd
import pytest

from drift_monitor.drift import FEATURE_COLUMNS
from drift_monitor.loki import (
    events_to_frame,
    log_lines,
    prediction_events,
    query_range,
)


def test_every_line_of_every_stream_is_returned(loki_payload):
    lines = log_lines(loki_payload)

    assert len(lines) == 100
    assert all(isinstance(line, str) for line in lines)


def test_an_empty_answer_gives_no_lines():
    assert log_lines({"status": "success", "data": {"resultType": "streams", "result": []}}) == []
    assert log_lines({}) == []


def test_only_prediction_events_are_kept(loki_payload):
    events, skipped = prediction_events(log_lines(loki_payload))

    assert len(events) == 98
    # One "request" event and one line that was cut in half.
    assert skipped == 2
    assert {event["model_version"] for event in events} == {"3", "4"}


def test_a_line_that_is_not_json_is_counted_not_raised():
    events, skipped = prediction_events(["not json at all", '{"event": "prediction"}'])

    assert len(events) == 1
    assert skipped == 1


def test_the_events_become_a_table_of_features(loki_payload):
    events, _ = prediction_events(log_lines(loki_payload))
    frame = events_to_frame(events, FEATURE_COLUMNS)

    assert list(frame.columns) == FEATURE_COLUMNS
    assert len(frame) == 98
    assert all(pd.api.types.is_numeric_dtype(frame[column]) for column in FEATURE_COLUMNS)
    assert frame["Latitude"].between(32.0, 42.5).all()


def test_rows_with_a_missing_or_broken_feature_are_dropped():
    good = {name: 1.0 for name in FEATURE_COLUMNS}
    short = {name: 1.0 for name in FEATURE_COLUMNS[:-1]}
    text = {**good, "MedInc": "high"}

    frame = events_to_frame(
        [
            {"event": "prediction", "features": good},
            {"event": "prediction", "features": short},
            {"event": "prediction", "features": text},
            {"event": "prediction"},
        ],
        FEATURE_COLUMNS,
    )

    assert len(frame) == 1


def test_the_query_asks_loki_for_the_right_window(monkeypatch, loki_payload):
    """No network: the call is checked, the answer is the fixture."""
    seen = {}

    class Answer:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return loki_payload

    def fake_get(url, params, timeout):
        seen["url"] = url
        seen["params"] = params
        seen["timeout"] = timeout
        return Answer()

    monkeypatch.setattr("drift_monitor.loki.requests.get", fake_get)
    payload = query_range("http://loki:3100/", '{app="inference"}', window_minutes=30, limit=4000)

    assert payload == loki_payload
    assert seen["url"] == "http://loki:3100/loki/api/v1/query_range"
    assert seen["params"]["limit"] == 4000
    assert seen["params"]["direction"] == "backward"
    window = int(seen["params"]["end"]) - int(seen["params"]["start"])
    assert window == 30 * 60 * 1_000_000_000


def test_a_loki_error_is_raised(monkeypatch):
    class Answer:
        def raise_for_status(self):
            raise RuntimeError("502 Bad Gateway")

    monkeypatch.setattr("drift_monitor.loki.requests.get", lambda *a, **k: Answer())

    with pytest.raises(RuntimeError, match="502"):
        query_range("http://loki:3100", "{}", 60, 10)
