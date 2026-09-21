"""The command line: exit codes, and the promise that stdout is only JSON."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from tests.conftest import MODEL

from registry_ops.cli import main

SERVICE_ROOT = Path(__file__).resolve().parents[1]

AUDIT_KEYS = {
    "ts",
    "level",
    "event",
    "service",
    "action",
    "model",
    "version",
    "from_stage",
    "to_stage",
    "previous_production_version",
    "actor",
    "git_sha",
    "result",
    "error",
}


@pytest.fixture
def cli(client, tracking_uri, capsys, monkeypatch):
    """Run a command against the temporary registry and read its output back.

    Returns the exit code, the parsed JSON lines from stdout and stderr as
    text. Parsing every stdout line is itself part of the contract: a line
    that is not JSON makes the test fail.
    """
    monkeypatch.setenv("MODEL_NAME", MODEL)
    monkeypatch.setenv("ACTOR", "maks")
    monkeypatch.setenv("GIT_SHA", "0123abc")

    def run(*argv: str) -> tuple[int, list[dict], str]:
        code = main(["--tracking-uri", tracking_uri, *argv])
        captured = capsys.readouterr()
        lines = [json.loads(line) for line in captured.out.splitlines()]
        return code, lines, captured.err

    return run


def test_a_promotion_prints_one_audit_line_with_every_field(cli):
    code, lines, _ = cli("promote", "--version", "1")

    assert code == 0
    assert len(lines) == 1
    assert set(lines[0]) == AUDIT_KEYS
    assert lines[0]["event"] == "model_registry_audit"
    assert lines[0]["service"] == "registry-ops"
    assert lines[0]["action"] == "promote"
    assert lines[0]["model"] == MODEL
    assert lines[0]["actor"] == "maks"
    assert lines[0]["git_sha"] == "0123abc"


def test_a_second_promotion_prints_the_archive_line_first(cli):
    cli("promote", "--version", "1")
    code, lines, _ = cli("promote", "--version", "2")

    assert code == 0
    assert [line["action"] for line in lines] == ["archive", "promote"]
    assert [line["version"] for line in lines] == ["1", "2"]


def test_sync_is_idempotent(cli):
    cli("promote", "--version", "2")
    code, lines, _ = cli("sync", "--production-version", "2")

    assert code == 0
    assert [line["action"] for line in lines] == ["no_change"]


def test_rollback_prints_a_rollback_line(cli):
    cli("promote", "--version", "1")
    cli("promote", "--version", "2")
    code, lines, _ = cli("rollback")

    assert code == 0
    assert [line["action"] for line in lines] == ["archive", "rollback"]


def test_deleting_the_production_version_fails_with_one_failure_line(cli, caplog):
    cli("promote", "--version", "1")
    code, lines, _ = cli("delete", "--version", "1")

    assert code == 1
    assert len(lines) == 1
    assert lines[0]["action"] == "delete"
    assert lines[0]["result"] == "failure"
    assert lines[0]["version"] == "1"
    assert "cannot be deleted" in lines[0]["error"]
    assert "cannot be deleted" in caplog.text


def test_promoting_a_missing_version_fails_with_one_failure_line(cli):
    code, lines, _ = cli("promote", "--version", "77")

    assert code == 1
    assert lines[0]["result"] == "failure"
    assert lines[0]["action"] == "promote"
    assert lines[0]["to_stage"] is None


def test_the_list_table_goes_to_stderr_and_stdout_stays_empty(cli):
    cli("promote", "--version", "1")
    code, lines, stderr = cli("list")

    assert code == 0
    assert lines == []
    assert "version" in stderr
    assert "production" in stderr


def test_a_failing_list_writes_no_audit_line(cli, caplog):
    code, lines, _ = cli("--model-name", "not-a-model", "list")

    assert code == 1
    assert lines == []
    assert "no versions" in caplog.text


def test_the_tool_runs_as_a_module(tracking_uri, client):
    """The container starts it as `python -m registry_ops`."""
    finished = subprocess.run(
        [
            sys.executable,
            "-m",
            "registry_ops",
            "--tracking-uri",
            tracking_uri,
            "--model-name",
            MODEL,
            "promote",
            "--version",
            "3",
        ],
        cwd=SERVICE_ROOT,
        capture_output=True,
        text=True,
        env=dict(os.environ, ACTOR="ci", GIT_SHA="feedbee"),
        timeout=120,
    )

    assert finished.returncode == 0, finished.stderr
    line = json.loads(finished.stdout.strip())
    assert line["action"] == "promote"
    assert line["version"] == "3"
    assert line["actor"] == "ci"
