"""The shapes of the requests and the responses.

The ranges are the ones the California Housing data really has, with some room
on both sides. They are the first line of defence: a value far outside them is
either a mistake or an attack, and the model would answer with a number that
looks fine but means nothing.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# The order the model was trained with. It has to stay exactly this, because
# the pipeline gets a DataFrame and scikit-learn checks the column names.
FEATURE_COLUMNS = [
    "MedInc",
    "HouseAge",
    "AveRooms",
    "AveBedrms",
    "Population",
    "AveOccup",
    "Latitude",
    "Longitude",
]

# strict=True keeps strings like "8.3" out. A whole number is still fine:
# pydantic accepts an int where a float is asked for.
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class PredictRequest(BaseModel):
    """One block group of the California Housing data."""

    # extra="forbid" turns an unknown field into an error. A misspelled name
    # would otherwise be dropped in silence and the model would use a default.
    model_config = ConfigDict(extra="forbid")

    MedInc: Number = Field(ge=0, le=20, description="median income, in tens of thousands")
    HouseAge: Number = Field(ge=0, le=100, description="median age of the houses, in years")
    AveRooms: Number = Field(gt=0, le=200, description="average rooms per household")
    AveBedrms: Number = Field(gt=0, le=50, description="average bedrooms per household")
    Population: Number = Field(ge=1, le=50_000, description="people living in the block group")
    AveOccup: Number = Field(gt=0, le=1500, description="average people per household")
    Latitude: Number = Field(ge=32, le=42.5, description="latitude, California only")
    Longitude: Number = Field(ge=-125, le=-114, description="longitude, California only")

    def as_row(self) -> dict[str, float]:
        """The features as one row, in the order the model expects."""
        values = self.model_dump()
        return {column: values[column] for column in FEATURE_COLUMNS}


class PredictResponse(BaseModel):
    """The answer of `/predict`. The price is in units of $100,000."""

    # Pydantic reserves names starting with "model_" for itself. These two are
    # part of the agreed API, so that protection is switched off here.
    model_config = ConfigDict(protected_namespaces=())

    prediction: float
    model_name: str
    model_version: str
    request_id: str


class FieldError(BaseModel):
    """One rejected field. The value itself is never sent back."""

    field: str
    message: str


class ValidationErrorResponse(BaseModel):
    error: str = "validation_error"
    detail: list[FieldError]
    request_id: str


class ErrorResponse(BaseModel):
    """Every other error. It says as little as possible on purpose."""

    error: str
    detail: str
    request_id: str


class HealthResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    status: str
    model_version: str | None = None
    reason: str | None = None


class InfoResponse(BaseModel):
    """What is loaded right now. Used by people and by the demo screenshots."""

    model_config = ConfigDict(protected_namespaces=())

    status: str
    model_name: str
    model_version: str | None = None
    model_alias: str | None = None
    model_sha256: str | None = None
    git_sha: str | None = None
    run_id: str | None = None
    loaded_at: str | None = None
