"""Command line of the tool: `python -m registry_ops <command>`.

stdout carries the audit lines and nothing else. Every message a person reads,
including the table of the `list` command, goes to stderr together with the
log. That keeps one simple rule for whoever reads the output: every line on
stdout is JSON.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from mlflow.tracking import MlflowClient

from registry_ops.actions import (
    DELETE,
    PROMOTE,
    ROLLBACK,
    ActionError,
    delete,
    list_versions,
    promote,
    rollback,
    sync,
)
from registry_ops.audit import FAILURE, audit_line, emit
from registry_ops.registry import Settings

DEFAULT_MODEL_NAME = "california-housing"
UNKNOWN = "unknown"

TABLE_COLUMNS = ["version", "stage", "aliases", "rmse", "git_sha", "model_sha256", "run_id"]

log = logging.getLogger("registry-ops")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="registry_ops",
        description="Move model versions in the MLflow Model Registry.",
    )
    parser.add_argument("--tracking-uri", default=os.environ.get("MLFLOW_TRACKING_URI"))
    parser.add_argument("--model-name", default=os.environ.get("MODEL_NAME", DEFAULT_MODEL_NAME))
    parser.add_argument(
        "--actor",
        default=os.environ.get("ACTOR", UNKNOWN),
        help="who asked for the change, written into the audit line",
    )
    parser.add_argument("--git-sha", default=os.environ.get("GIT_SHA", UNKNOWN))

    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="show every version with its stage and aliases")

    promote_parser = commands.add_parser("promote", help="make a version the production one")
    promote_parser.add_argument("--version", required=True)

    rollback_parser = commands.add_parser(
        "rollback", help="go back to the previous-production version"
    )
    rollback_parser.add_argument("--version", help="roll back to this version instead")

    delete_parser = commands.add_parser("delete", help="remove a version that is not in production")
    delete_parser.add_argument("--version", required=True)

    sync_parser = commands.add_parser(
        "sync", help="make production match a version, doing nothing when it already does"
    )
    sync_parser.add_argument("--production-version", required=True)

    return parser.parse_args(argv)


def render_table(rows: list[dict[str, str]]) -> str:
    """The `list` output as a plain text table."""
    widths = {
        column: max(len(column), *(len(row[column]) for row in rows)) for column in TABLE_COLUMNS
    }
    header = "  ".join(column.ljust(widths[column]) for column in TABLE_COLUMNS)
    lines = [header, "  ".join("-" * widths[column] for column in TABLE_COLUMNS)]
    lines += [
        "  ".join(row[column].ljust(widths[column]) for column in TABLE_COLUMNS) for row in rows
    ]
    return "\n".join(lines)


def run(args: argparse.Namespace, client: MlflowClient) -> int:
    """Carry out one command and print its audit lines."""
    settings = Settings(model_name=args.model_name, actor=args.actor, git_sha=args.git_sha)

    if args.command == "list":
        print(render_table(list_versions(client, settings.model_name)), file=sys.stderr)
        return 0

    if args.command == "promote":
        lines = promote(client, settings, args.version)
    elif args.command == "rollback":
        lines = rollback(client, settings, args.version)
    elif args.command == "delete":
        lines = delete(client, settings, args.version)
    else:
        lines = sync(client, settings, args.production_version)

    for line in lines:
        emit(line)
    return 0


def failed_action(command: str) -> str:
    """The action name to put in the audit line of a failed command."""
    return {"promote": PROMOTE, "rollback": ROLLBACK, "delete": DELETE}.get(command, "sync")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    args = parse_args(argv)
    client = MlflowClient(tracking_uri=args.tracking_uri, registry_uri=args.tracking_uri)

    try:
        return run(args, client)
    except ActionError as error:
        log.error("%s failed: %s", args.command, error)
        if args.command != "list":
            # A read only command changes nothing, so it writes no audit line.
            emit(
                audit_line(
                    failed_action(args.command),
                    args.model_name,
                    getattr(args, "version", None) or getattr(args, "production_version", None),
                    actor=args.actor,
                    git_sha=args.git_sha,
                    result=FAILURE,
                    error=str(error),
                )
            )
        return 1
    except Exception:
        log.exception("%s failed", args.command)
        return 1
