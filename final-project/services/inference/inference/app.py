"""The FastAPI app: routes, error handling, metrics and the model reloader.

The app is built by `create_app`, so the tests can build several apps with
different settings in one process.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import pandas as pd
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from inference.config import Settings
from inference.logging_setup import log_event, request_id_var
from inference.metrics import Metrics, build_metrics
from inference.model_store import (
    MlflowModelSource,
    ModelLoadError,
    ModelStore,
)
from inference.schemas import (
    ErrorResponse,
    FieldError,
    HealthResponse,
    InfoResponse,
    PredictRequest,
    PredictResponse,
    ValidationErrorResponse,
)

log = logging.getLogger("inference")

# Probes and metric scrapes come every few seconds. Counting them would hide
# the real traffic in the error rate, and logging them would fill Loki with
# lines nobody reads.
QUIET_PATHS = ("/metrics", "/health/live", "/health/ready")

GENERIC_ERROR = "the request could not be processed"
NOT_LOADED = "the model is not loaded yet"


def create_app(settings: Settings | None = None, store: ModelStore | None = None) -> FastAPI:
    """Build the app. Without arguments everything comes from the environment."""
    settings = settings or Settings.from_env()
    metrics = build_metrics()
    if store is None:
        store = ModelStore(settings, MlflowModelSource(settings.tracking_uri))

    limiter = Limiter(key_func=get_remote_address, default_limits=[])

    app = FastAPI(
        title="California Housing inference",
        description="Predicts the median house value of a block group.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.store = store
    app.state.metrics = metrics
    app.state.limiter = limiter
    # Why readiness is still 503. It is None while everything is fine.
    app.state.load_failure = None

    register_middleware(app)
    register_routes(app, limiter)
    register_error_handlers(app)

    Instrumentator(registry=metrics.registry, excluded_handlers=["/metrics"]).instrument(
        app
    ).expose(app, endpoint="/metrics", include_in_schema=False)
    return app


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load the model at startup and keep checking for a newer one."""
    settings: Settings = app.state.settings
    log_event(
        log,
        "startup",
        "the service is starting",
        model_name=settings.model_name,
        model_source=settings.model_source,
        rate_limit=settings.rate_limit,
        fault_rate=settings.fault_rate,
        reload_seconds=settings.reload_seconds,
    )
    # The first attempt is awaited, so a pod that starts is either ready or
    # has said in the log why it is not.
    await asyncio.to_thread(reload_model, app)

    task = asyncio.create_task(reload_loop(app))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        app.state.store.close()
        log_event(log, "shutdown", "the service is stopping")


async def reload_loop(app: FastAPI) -> None:
    """Ask the registry every few seconds whether the alias moved."""
    seconds: float = app.state.settings.reload_seconds
    while True:
        await asyncio.sleep(seconds)
        await asyncio.to_thread(reload_model, app)


def reload_model(app: FastAPI) -> None:
    """One attempt to load or replace the model. Never raises.

    A failure here leaves the model that is already in use alone, so a pod
    that works keeps working even when MLflow is down.
    """
    settings: Settings = app.state.settings
    store: ModelStore = app.state.store
    metrics: Metrics = app.state.metrics

    try:
        loaded = store.refresh()
    except ModelLoadError as error:
        app.state.load_failure = error.reason
        metrics.load_failures.labels(reason=error.reason).inc()
        details = dict(error.details)
        # The version that was refused, not the one in use.
        attempted = details.pop("version", None)
        event = "checksum_mismatch" if error.reason == "checksum_mismatch" else "model_load_failed"
        log_event(
            log,
            event,
            str(error),
            level=logging.ERROR,
            model_version=attempted,
            reason=error.reason,
            **details,
        )
        return

    app.state.load_failure = None
    if loaded is None:
        return

    metrics.set_model_info(settings.model_name, loaded.version, loaded.model_sha256)
    log_event(
        log,
        "model_loaded",
        "the model is verified and ready",
        model_version=loaded.version,
        model_name=settings.model_name,
        model_alias=settings.model_alias,
        model_sha256=loaded.model_sha256,
        git_sha=loaded.git_sha,
        run_id=loaded.run_id,
        loaded_at=loaded.loaded_at,
    )


def register_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def track_request(request: Request, call_next):
        """Give the request an id, time it, count it and log it."""
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            record_request(app, request, 500, time.perf_counter() - started)
            raise
        else:
            response.headers["X-Request-ID"] = request_id
            record_request(app, request, response.status_code, time.perf_counter() - started)
            return response
        finally:
            request_id_var.reset(token)


def record_request(app: FastAPI, request: Request, status_code: int, seconds: float) -> None:
    if request.url.path in QUIET_PATHS:
        return

    version = current_version(app)
    app.state.metrics.observe_request(version, status_code, seconds)
    log_event(
        log,
        "request",
        model_version=version,
        method=request.method,
        path=request.url.path,
        status=status_code,
        latency_ms=round(seconds * 1000, 2),
    )


def register_routes(app: FastAPI, limiter: Limiter) -> None:
    settings: Settings = app.state.settings

    @app.get("/health/live", response_model=HealthResponse)
    def live() -> HealthResponse:
        """The process is running. It says nothing about the model."""
        return HealthResponse(status="alive")

    @app.get("/health/ready", response_model=HealthResponse)
    def ready(response: Response) -> HealthResponse:
        """Ready means: a model is loaded and its checksum was correct."""
        loaded = app.state.store.current
        if loaded is None:
            response.status_code = 503
            return HealthResponse(status="not_ready", reason=app.state.load_failure or "no_model")
        return HealthResponse(status="ready", model_version=loaded.version)

    @app.get("/info", response_model=InfoResponse)
    def info() -> InfoResponse:
        """Which model this pod serves, and where it came from."""
        loaded = app.state.store.current
        if loaded is None:
            return InfoResponse(
                status="not_ready",
                model_name=settings.model_name,
                model_alias=settings.model_alias,
            )
        return InfoResponse(
            status="ready",
            model_name=settings.model_name,
            model_version=loaded.version,
            model_alias=settings.model_alias,
            model_sha256=loaded.model_sha256,
            git_sha=loaded.git_sha,
            run_id=loaded.run_id,
            loaded_at=loaded.loaded_at,
        )

    @app.post(
        "/predict",
        response_model=PredictResponse,
        responses={
            400: {"model": ValidationErrorResponse},
            429: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    @limiter.limit(settings.rate_limit)
    def predict(request: Request, body: PredictRequest):
        """One prediction. The answer is in units of $100,000."""
        return run_prediction(app, request, body)


def run_prediction(app: FastAPI, request: Request, body: PredictRequest):
    settings: Settings = app.state.settings
    loaded = app.state.store.current
    if loaded is None:
        raise HTTPException(status_code=503, detail=NOT_LOADED)

    if settings.fault_rate > 0 and random.random() < settings.fault_rate:
        # Fault injection for the canary demo, see FAULT_RATE in the README.
        log_event(
            log,
            "fault_injected",
            "answering with an error on purpose",
            level=logging.WARNING,
            model_version=loaded.version,
        )
        return error_response(request, 500, "internal_error", GENERIC_ERROR)

    features = body.as_row()
    started = time.perf_counter()
    value = float(loaded.model.predict(pd.DataFrame([features]))[0])
    latency_ms = round((time.perf_counter() - started) * 1000, 2)

    app.state.metrics.observe_prediction(loaded.version, value)
    # The drift job reads this event back from Loki, so the feature names have
    # to stay exactly the ones the model was trained with.
    log_event(
        log,
        "prediction",
        model_version=loaded.version,
        features=features,
        prediction=value,
        latency_ms=latency_ms,
    )
    return PredictResponse(
        prediction=value,
        model_name=settings.model_name,
        model_version=loaded.version,
        request_id=request_id_of(request),
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def on_invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        """Refused input. The values that were sent never come back."""
        fields = [
            FieldError(field=field_name(item["loc"]), message=item["msg"])
            for item in error.errors()
        ]
        log_event(
            log,
            "validation_error",
            level=logging.WARNING,
            model_version=current_version(app),
            path=request.url.path,
            fields=[item.field for item in fields],
        )
        body = ValidationErrorResponse(detail=fields, request_id=request_id_of(request))
        return JSONResponse(status_code=400, content=body.model_dump())

    @app.exception_handler(RateLimitExceeded)
    async def on_rate_limit(request: Request, error: RateLimitExceeded) -> JSONResponse:
        log_event(
            log,
            "rate_limited",
            level=logging.WARNING,
            model_version=current_version(app),
            path=request.url.path,
            limit=app.state.settings.rate_limit,
        )
        return error_response(request, 429, "rate_limited", "too many requests, try again later")

    @app.exception_handler(HTTPException)
    async def on_http_error(request: Request, error: HTTPException) -> JSONResponse:
        if error.status_code == 500:
            # A 500 says nothing at all: the cause is only in our log.
            return error_response(request, 500, "internal_error", GENERIC_ERROR)
        name = "model_not_ready" if error.status_code == 503 else "request_failed"
        return error_response(request, error.status_code, name, str(error.detail))

    @app.exception_handler(Exception)
    async def on_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        """Anything we did not think of. The client only gets the request id."""
        log_event(
            log,
            "internal_error",
            "the request failed",
            level=logging.ERROR,
            exc_info=True,
            model_version=current_version(app),
            path=request.url.path,
        )
        return error_response(request, 500, "internal_error", GENERIC_ERROR)


def error_response(request: Request, status_code: int, error: str, detail: str) -> JSONResponse:
    body = ErrorResponse(error=error, detail=detail, request_id=request_id_of(request))
    return JSONResponse(status_code=status_code, content=body.model_dump())


def request_id_of(request: Request) -> str:
    """The id of the request being answered, also on the error paths."""
    return getattr(request.state, "request_id", None) or request_id_var.get() or "unknown"


def current_version(app: FastAPI) -> str | None:
    loaded = app.state.store.current
    return loaded.version if loaded is not None else None


def field_name(location: tuple) -> str:
    """Turn the position pydantic reports into a field name.

    Only names are kept. A body that is not even JSON is reported at the
    character where parsing stopped, and that number says nothing useful.
    """
    parts = [part for part in location if isinstance(part, str) and part != "body"]
    return ".".join(parts) if parts else "body"
