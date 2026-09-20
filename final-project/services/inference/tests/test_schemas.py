"""Tests for the request model: what is accepted and what is refused."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from inference.schemas import FEATURE_COLUMNS, PredictRequest

VALID = {
    "MedInc": 8.3252,
    "HouseAge": 41.0,
    "AveRooms": 6.9841,
    "AveBedrms": 1.0238,
    "Population": 322.0,
    "AveOccup": 2.5556,
    "Latitude": 37.88,
    "Longitude": -122.23,
}


def test_a_normal_block_group_is_accepted():
    request = PredictRequest(**VALID)

    assert request.MedInc == pytest.approx(8.3252)
    assert list(request.as_row()) == FEATURE_COLUMNS
    assert request.as_row()["Longitude"] == pytest.approx(-122.23)


def test_whole_numbers_are_accepted_for_a_float_field():
    request = PredictRequest(**{**VALID, "HouseAge": 41, "Population": 322})

    assert request.HouseAge == 41.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("MedInc", -1.0),
        ("MedInc", 25.0),
        ("HouseAge", -0.5),
        ("HouseAge", 120.0),
        ("AveRooms", 0.0),
        ("AveRooms", 500.0),
        ("AveBedrms", 0.0),
        ("AveBedrms", 60.0),
        ("Population", 0.0),
        ("Population", 60_000.0),
        ("AveOccup", 0.0),
        ("AveOccup", 2000.0),
        ("Latitude", 10.0),
        ("Latitude", 50.0),
        ("Longitude", -200.0),
        ("Longitude", 0.0),
    ],
)
def test_a_value_outside_the_range_of_california_is_refused(field, value):
    with pytest.raises(ValidationError) as error:
        PredictRequest(**{**VALID, field: value})

    assert error.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("value", ["8.3252", True, None, [1.0]])
def test_a_value_that_is_not_a_number_is_refused(value):
    """Strings are refused on purpose: a client must send real numbers."""
    with pytest.raises(ValidationError):
        PredictRequest(**{**VALID, "MedInc": value})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nan_and_infinity_are_refused(value):
    with pytest.raises(ValidationError):
        PredictRequest(**{**VALID, "AveOccup": value})


def test_a_missing_field_is_refused():
    body = dict(VALID)
    del body["Latitude"]

    with pytest.raises(ValidationError) as error:
        PredictRequest(**body)

    assert error.value.errors()[0]["loc"] == ("Latitude",)


def test_an_unknown_field_is_refused():
    with pytest.raises(ValidationError) as error:
        PredictRequest(**{**VALID, "Surprise": 1.0})

    assert error.value.errors()[0]["loc"] == ("Surprise",)


def test_the_row_keeps_the_order_the_model_was_trained_with():
    shuffled = dict(reversed(list(VALID.items())))

    assert list(PredictRequest(**shuffled).as_row()) == FEATURE_COLUMNS
