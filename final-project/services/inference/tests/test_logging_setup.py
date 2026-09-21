"""Tests for the JSON log format."""

from __future__ import annotations

import json
import logging

import pytest

from inference.logging_setup import JsonFormatter, log_event, request_id_var

BASE_KEYS = {"ts", "level", "event", "service", "request_id", "model_version"}


@pytest.fixture
def logger(log_reader):
    token = request_id_var.set(None)
    yield logging.getLogger("test")
    request_id_var.reset(token)


def test_every_line_is_one_json_object_with_the_agreed_keys(logger, log_reader):
    log_event(logger, "startup", model_version="3", model_name="california-housing")

    (line,) = log_reader.lines()
    assert set(line) >= BASE_KEYS
    assert line["event"] == "startup"
    assert line["service"] == "inference"
    assert line["level"] == "info"
    assert line["model_version"] == "3"
    assert line["model_name"] == "california-housing"
    assert line["ts"].endswith("Z")


def test_the_model_version_is_null_when_no_model_is_loaded(logger, log_reader):
    log_event(logger, "startup")

    assert log_reader.lines()[0]["model_version"] is None


def test_the_request_id_of_the_current_request_is_added(logger, log_reader):
    request_id_var.set("abc-123")

    log_event(logger, "request", path="/predict")

    assert log_reader.last("request")["request_id"] == "abc-123"


def test_a_message_and_a_level_are_kept(logger, log_reader):
    log_event(
        logger,
        "checksum_mismatch",
        "the model file is not the trained one",
        level=logging.ERROR,
    )

    line = log_reader.last("checksum_mismatch")
    assert line["level"] == "error"
    assert line["message"] == "the model file is not the trained one"


def test_an_exception_is_written_as_text_fields(logger, log_reader):
    try:
        raise ValueError("broken")
    except ValueError:
        log_event(logger, "internal_error", level=logging.ERROR, exc_info=True)

    line = log_reader.last("internal_error")
    assert line["error"] == "ValueError: broken"
    assert "ValueError: broken" in line["traceback"]


def test_a_log_record_from_a_library_still_comes_out_as_json(logger, log_reader):
    logging.getLogger("uvicorn.error").warning("something happened")

    line = log_reader.last("uvicorn.error")
    assert line["message"] == "something happened"


def test_the_plain_access_log_of_uvicorn_is_switched_off(logger):
    assert logging.getLogger("uvicorn.access").disabled is True


def test_a_value_that_is_not_json_keeps_the_line_readable():
    record = logging.LogRecord("test", logging.INFO, "f.py", 1, "", None, None)
    record.event = "prediction"
    record.fields = {"value": object()}

    line = json.loads(JsonFormatter().format(record))
    assert line["event"] == "prediction"
    assert isinstance(line["value"], str)
