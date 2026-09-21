"""The audit line that every state-changing command prints.

One command run prints one line per action it performed. The line is JSON, it
goes to stdout, and it always has the same keys in the same order. In the
cluster the tool runs as an ArgoCD hook Job, so these lines end up in Loki and
answer the question "who moved which model version to production, and when".
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import IO

AUDIT_EVENT = "model_registry_audit"
SERVICE = "registry-ops"

SUCCESS = "success"
FAILURE = "failure"


def utc_now_iso() -> str:
    """The current time as an ISO string in UTC, e.g. 2026-09-20T18:30:00Z."""
    now = datetime.now(UTC).isoformat(timespec="milliseconds")
    return now.replace("+00:00", "Z")


def audit_line(
    action: str,
    model: str,
    version: str | None,
    *,
    actor: str,
    git_sha: str,
    from_stage: str | None = None,
    to_stage: str | None = None,
    previous_production_version: str | None = None,
    result: str = SUCCESS,
    error: str | None = None,
) -> dict[str, object]:
    """Build one audit record.

    `previous_production_version` is the version the alias `previous-production`
    points at once the action is done, that is the version a rollback would
    bring back.
    """
    # "level" is here for the log tools. Without it Loki guesses the level from
    # the text, finds the key "error" in every line and marks a successful
    # promotion as an error.
    return {
        "ts": utc_now_iso(),
        "level": "info" if result == SUCCESS else "error",
        "event": AUDIT_EVENT,
        "service": SERVICE,
        "action": action,
        "model": model,
        "version": version,
        "from_stage": from_stage,
        "to_stage": to_stage,
        "previous_production_version": previous_production_version,
        "actor": actor,
        "git_sha": git_sha,
        "result": result,
        "error": error,
    }


def emit(line: dict[str, object], stream: IO[str] | None = None) -> None:
    """Write one audit line as JSON. Nothing else is ever written to stdout."""
    target = sys.stdout if stream is None else stream
    print(json.dumps(line), file=target, flush=True)
