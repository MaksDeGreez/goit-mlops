"""Reading the prediction events of the inference service back from Loki.

The inference service prints one JSON object per prediction. Loki stores those
lines as they are, so the job asks for a time window and parses each line back
into a row of features.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pandas as pd
import requests

QUERY_PATH = "/loki/api/v1/query_range"
PREDICTION_EVENT = "prediction"
FEATURES_FIELD = "features"

NANOSECONDS_PER_MINUTE = 60 * 1_000_000_000


def log_lines(payload: dict[str, Any]) -> list[str]:
    """Every log line of every stream in a query_range answer.

    A stream holds `values: [[<nanosecond timestamp as a string>, <line>], ...]`.
    With `| json` in the query Loki adds labels but leaves the line untouched,
    so the line is still the JSON object the service printed.
    """
    streams = payload.get("data", {}).get("result", [])
    return [line for stream in streams for _, line in stream.get("values", [])]


def prediction_events(lines: list[str]) -> tuple[list[dict[str, Any]], int]:
    """Parse the lines and keep the prediction events.

    Returns the events and the number of lines that could not be used. A log
    pipeline collects more than one kind of line, and a line can be cut in the
    middle, so anything unexpected is counted instead of stopping the job.
    """
    events = []
    skipped = 0
    for line in lines:
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            skipped += 1
            continue
        if not isinstance(event, dict) or event.get("event") != PREDICTION_EVENT:
            skipped += 1
            continue
        events.append(event)
    return events, skipped


def events_to_frame(events: list[dict[str, Any]], columns: list[str]) -> pd.DataFrame:
    """Turn prediction events into a table of features.

    Rows without every feature, or with a value that is not a number, are
    dropped: a half filled row would move the drift score for no good reason.
    """
    rows = []
    for event in events:
        features = event.get(FEATURES_FIELD)
        if not isinstance(features, dict):
            continue
        rows.append({column: features.get(column) for column in columns})

    frame = pd.DataFrame(rows, columns=columns)
    for column in columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna().reset_index(drop=True)


def query_range(
    url: str,
    query: str,
    window_minutes: int,
    limit: int,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Ask Loki for the log lines of the last `window_minutes` minutes."""
    end = time.time_ns()
    start = end - window_minutes * NANOSECONDS_PER_MINUTE
    response = requests.get(
        url.rstrip("/") + QUERY_PATH,
        params={
            "query": query,
            "start": str(start),
            "end": str(end),
            "limit": limit,
            "direction": "backward",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()
