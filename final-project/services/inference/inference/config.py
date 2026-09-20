"""Every setting of the service, read once from the environment.

The service is started by Kubernetes, so there are no command line options:
a Deployment sets environment variables. Bad values stop the process at once
instead of showing up later as strange behaviour.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_MODEL_NAME = "california-housing"
DEFAULT_MODEL_ALIAS = "staging"
DEFAULT_RELOAD_SECONDS = 60.0
DEFAULT_RATE_LIMIT = "20/second"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_PORT = 8000

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class Settings:
    """What the service needs to know. Built by `Settings.from_env`."""

    model_name: str = DEFAULT_MODEL_NAME
    # Exactly one of these two is set. A version pins the model, an alias
    # follows whatever the registry points at.
    model_version: str | None = None
    model_alias: str | None = DEFAULT_MODEL_ALIAS
    # Optional second checksum, taken from git. It is stronger than the tag in
    # the registry, because it does not trust the registry at all.
    model_sha256: str | None = None
    reload_seconds: float = DEFAULT_RELOAD_SECONDS
    tracking_uri: str | None = None
    rate_limit: str = DEFAULT_RATE_LIMIT
    fault_rate: float = 0.0
    log_level: str = DEFAULT_LOG_LEVEL
    port: int = DEFAULT_PORT

    @property
    def model_source(self) -> str:
        """Short text for the logs: where the model comes from."""
        if self.model_version:
            return f"version {self.model_version}"
        return f"alias {self.model_alias}"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        values = os.environ if env is None else env

        version = _text(values, "MODEL_VERSION")
        alias = _text(values, "MODEL_ALIAS")
        if version:
            # A pinned version wins. Production pins the version in git, and a
            # left over alias must not quietly change the model under it.
            alias = None
        elif not alias:
            alias = DEFAULT_MODEL_ALIAS

        return cls(
            model_name=_text(values, "MODEL_NAME") or DEFAULT_MODEL_NAME,
            model_version=version,
            model_alias=alias,
            model_sha256=_sha256(values),
            reload_seconds=_positive_float(values, "MODEL_RELOAD_SECONDS", DEFAULT_RELOAD_SECONDS),
            tracking_uri=_text(values, "MLFLOW_TRACKING_URI"),
            rate_limit=_text(values, "RATE_LIMIT") or DEFAULT_RATE_LIMIT,
            fault_rate=_fault_rate(values),
            log_level=(_text(values, "LOG_LEVEL") or DEFAULT_LOG_LEVEL).upper(),
            port=_port(values),
        )


def _text(env: Mapping[str, str], name: str) -> str | None:
    """The value of a variable, or None when it is missing or empty.

    An empty value means "not set" here. Helm charts write empty strings for
    settings that were left out, and they should not count as a real value.
    """
    value = env.get(name, "").strip()
    return value or None


def _sha256(env: Mapping[str, str]) -> str | None:
    value = _text(env, "MODEL_SHA256")
    if value is None:
        return None
    value = value.lower()
    if not SHA256_PATTERN.match(value):
        raise ValueError("MODEL_SHA256 must be 64 hex characters")
    return value


def _positive_float(env: Mapping[str, str], name: str, default: float) -> float:
    value = _text(env, name)
    if value is None:
        return default
    number = float(value)
    if number <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return number


def _fault_rate(env: Mapping[str, str]) -> float:
    value = _text(env, "FAULT_RATE")
    if value is None:
        return 0.0
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ValueError("FAULT_RATE must be between 0 and 1")
    return number


def _port(env: Mapping[str, str]) -> int:
    value = _text(env, "PORT")
    return int(value) if value else DEFAULT_PORT
