"""JSON logs on stdout, one object per line.

Loki collects these lines from the pod and the drift job reads the
`prediction` events back out of Loki, so the format is part of the contract
between the services, not only something for people to read.

Every line has the same first keys: `ts`, `level`, `event`, `service`,
`request_id`, `model_version`. After them come the fields of the event.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, TextIO

SERVICE_NAME = "inference"

# The id of the request that is being answered right now. A context variable
# keeps it separate per request without passing it through every function.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def utc_now() -> str:
    """The current time as `2026-09-20T18:30:00.123Z`."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class JsonFormatter(logging.Formatter):
    """Turns a log record into one JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        fields: dict[str, Any] = dict(getattr(record, "fields", {}))
        line: dict[str, Any] = {
            "ts": utc_now(),
            "level": record.levelname.lower(),
            # Records from libraries have no event of their own, so the name of
            # the logger is used instead.
            "event": getattr(record, "event", record.name),
            "service": SERVICE_NAME,
            "request_id": request_id_var.get(),
            "model_version": fields.pop("model_version", None),
        }

        message = record.getMessage()
        if message:
            line["message"] = message
        if record.exc_info:
            error = record.exc_info[1]
            line["error"] = f"{type(error).__name__}: {error}"
            # The traceback stays in the log, where only we can read it. It is
            # never part of an answer to a client.
            line["traceback"] = self.formatException(record.exc_info)

        line.update(fields)
        # default=str keeps one odd value from killing the whole log line.
        return json.dumps(line, default=str)


def configure_logging(level: str = "INFO", stream: TextIO | None = None) -> None:
    """Send every log record to stdout as JSON.

    `stream` is only there for the tests, which read the lines back.
    """
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # We log every request ourselves, with the request id and the latency in
    # it. The plain text access log of uvicorn would only repeat that in a
    # format Loki cannot parse.
    logging.getLogger("uvicorn.access").disabled = True


def log_event(
    logger: logging.Logger,
    event: str,
    message: str = "",
    level: int = logging.INFO,
    exc_info: bool = False,
    **fields: Any,
) -> None:
    """Write one event. Extra keyword arguments become fields of the line."""
    logger.log(level, message, exc_info=exc_info, extra={"event": event, "fields": fields})
