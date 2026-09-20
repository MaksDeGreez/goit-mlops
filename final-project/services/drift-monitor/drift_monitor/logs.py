"""Structured logs: one JSON object per line on stdout.

The inference service writes its logs in the same shape, so Loki and Grafana
treat both services the same way and one LogQL query can filter on `event`.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import IO

SERVICE = "drift-monitor"


def utc_now_iso() -> str:
    """The current time as an ISO string in UTC, e.g. 2026-09-20T18:30:00Z."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def log_record(event: str, level: str = "INFO", **fields: object) -> dict[str, object]:
    return {
        "ts": utc_now_iso(),
        "level": level,
        "event": event,
        "service": SERVICE,
        **fields,
    }


def log(event: str, level: str = "INFO", stream: IO[str] | None = None, **fields: object) -> None:
    print(
        json.dumps(log_record(event, level, **fields), default=str),
        file=sys.stdout if stream is None else stream,
        flush=True,
    )
