"""Tests for reading the settings from the environment."""

from __future__ import annotations

import pytest

from inference.config import Settings

SHA = "f" * 64


def test_an_empty_environment_gives_the_documented_defaults():
    settings = Settings.from_env({})

    assert settings.model_name == "california-housing"
    assert settings.model_alias == "staging"
    assert settings.model_version is None
    assert settings.model_sha256 is None
    assert settings.reload_seconds == 60.0
    assert settings.rate_limit == "20/second"
    assert settings.fault_rate == 0.0
    assert settings.port == 8000


def test_an_alias_can_be_chosen():
    settings = Settings.from_env({"MODEL_ALIAS": "production"})

    assert settings.model_alias == "production"
    assert settings.model_version is None
    assert settings.model_source == "alias production"


def test_a_pinned_version_wins_over_an_alias():
    settings = Settings.from_env({"MODEL_VERSION": "7", "MODEL_ALIAS": "staging"})

    assert settings.model_version == "7"
    assert settings.model_alias is None
    assert settings.model_source == "version 7"


def test_empty_values_count_as_not_set():
    """Helm writes an empty string for a value that was left out."""
    settings = Settings.from_env({"MODEL_VERSION": "  ", "MODEL_NAME": "", "MODEL_ALIAS": ""})

    assert settings.model_name == "california-housing"
    assert settings.model_alias == "staging"
    assert settings.model_version is None


def test_the_model_checksum_is_read_and_lowercased():
    settings = Settings.from_env({"MODEL_SHA256": SHA.upper()})

    assert settings.model_sha256 == SHA


@pytest.mark.parametrize("value", ["not-a-hash", "abc", "g" * 64, SHA + "00"])
def test_a_model_checksum_that_is_not_a_sha256_is_refused(value):
    with pytest.raises(ValueError, match="MODEL_SHA256"):
        Settings.from_env({"MODEL_SHA256": value})


def test_the_other_values_are_read():
    settings = Settings.from_env(
        {
            "MODEL_NAME": "other-model",
            "MLFLOW_TRACKING_URI": "http://mlflow:5000",
            "MODEL_RELOAD_SECONDS": "5",
            "RATE_LIMIT": "3/minute",
            "FAULT_RATE": "0.25",
            "LOG_LEVEL": "debug",
            "PORT": "9000",
        }
    )

    assert settings.model_name == "other-model"
    assert settings.tracking_uri == "http://mlflow:5000"
    assert settings.reload_seconds == 5.0
    assert settings.rate_limit == "3/minute"
    assert settings.fault_rate == 0.25
    assert settings.log_level == "DEBUG"
    assert settings.port == 9000


@pytest.mark.parametrize("value", ["-0.1", "1.5", "two"])
def test_a_fault_rate_outside_zero_to_one_is_refused(value):
    with pytest.raises(ValueError):
        Settings.from_env({"FAULT_RATE": value})


@pytest.mark.parametrize("value", ["0", "-5", "nonsense"])
def test_a_reload_interval_that_is_not_positive_is_refused(value):
    with pytest.raises(ValueError):
        Settings.from_env({"MODEL_RELOAD_SECONDS": value})
