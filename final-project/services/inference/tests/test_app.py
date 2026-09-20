"""Tests for the HTTP API.

The model is a real, very small scikit-learn pipeline, handed to the app by a
fake source (see conftest.py). Nothing here talks to a network.
"""

from __future__ import annotations

import time
from dataclasses import replace

import pytest
from conftest import GIT_SHA, RUN_ID, VALID_REQUEST, CountingLoader, FakeSource
from fastapi.testclient import TestClient

from inference.app import create_app
from inference.config import Settings
from inference.model_store import ModelStore, load_sklearn_model
from inference.schemas import FEATURE_COLUMNS

WRONG_SHA256 = "a" * 64


@pytest.fixture
def build(saved_model_dir, saved_model_sha256, log_reader):
    """Build an app with a fake registry behind it."""
    built = []

    def factory(**options):
        source = FakeSource(saved_model_dir, saved_model_sha256)
        loader = CountingLoader(load_sklearn_model)
        settings = Settings(**options)
        store = ModelStore(settings, source, loader)
        app = create_app(settings, store)
        built.append((app, source, loader))
        return app, source, loader

    return factory


@pytest.fixture
def client(build):
    app, source, loader = build()
    with TestClient(app) as test_client:
        test_client.source = source
        test_client.loader = loader
        yield test_client


def metrics_text(client: TestClient) -> str:
    return client.get("/metrics").text


def test_a_valid_request_gets_a_prediction(client):
    response = client.post("/predict", json=VALID_REQUEST)

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["prediction"], float)
    assert body["model_name"] == "california-housing"
    assert body["model_version"] == "1"
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_the_client_can_choose_the_request_id(client):
    response = client.post("/predict", json=VALID_REQUEST, headers={"X-Request-ID": "trace-42"})

    assert response.json()["request_id"] == "trace-42"


def test_the_service_is_alive_and_ready_once_the_model_is_loaded(client):
    assert client.get("/health/live").json() == {
        "status": "alive",
        "model_version": None,
        "reason": None,
    }

    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["model_version"] == "1"


def test_info_shows_where_the_model_came_from(client, saved_model_sha256):
    body = client.get("/info").json()

    assert body == {
        "status": "ready",
        "model_name": "california-housing",
        "model_version": "1",
        "model_alias": "staging",
        "model_sha256": saved_model_sha256,
        "git_sha": GIT_SHA,
        "run_id": RUN_ID,
        "loaded_at": body["loaded_at"],
    }
    assert body["loaded_at"].endswith("Z")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("MedInc", 99.0),
        ("Latitude", 10.0),
        ("Longitude", 0.0),
        ("AveRooms", 0.0),
        ("Population", -5.0),
        ("MedInc", "eight"),
        ("HouseAge", None),
    ],
)
def test_a_bad_value_is_refused_with_400_and_the_field_name(client, field, value):
    response = client.post("/predict", json={**VALID_REQUEST, field: value})

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "validation_error"
    assert body["detail"][0]["field"] == field
    assert body["detail"][0]["message"]


def test_a_missing_field_is_refused_with_400(client):
    body = dict(VALID_REQUEST)
    del body["AveOccup"]

    response = client.post("/predict", json=body)

    assert response.status_code == 400
    assert response.json()["detail"][0]["field"] == "AveOccup"


def test_an_unknown_field_is_refused_with_400(client):
    response = client.post("/predict", json={**VALID_REQUEST, "Surprise": 1.0})

    assert response.status_code == 400
    assert response.json()["detail"][0]["field"] == "Surprise"


def test_a_body_that_is_not_json_is_refused_with_400(client):
    response = client.post(
        "/predict",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "validation_error"
    assert response.json()["detail"][0]["field"] == "body"


def test_the_answer_never_contains_the_value_that_was_refused(client):
    """A secret sent by mistake must not come back in the error."""
    response = client.post("/predict", json={**VALID_REQUEST, "MedInc": "super-secret-value"})

    assert "super-secret-value" not in response.text
    assert "python" not in response.text.lower()
    assert "traceback" not in response.text.lower()


def test_the_log_of_a_refused_request_only_names_the_fields(client, log_reader):
    client.post("/predict", json={**VALID_REQUEST, "MedInc": "super-secret-value"})

    line = log_reader.last("validation_error")
    assert line["fields"] == ["MedInc"]
    assert "super-secret-value" not in str(line)


def test_too_many_requests_get_429_with_a_clean_body(build):
    app, _, _ = build(rate_limit="3/minute")
    with TestClient(app) as client:
        codes = [client.post("/predict", json=VALID_REQUEST).status_code for _ in range(5)]

        assert codes == [200, 200, 200, 429, 429]
        body = client.post("/predict", json=VALID_REQUEST).json()
        assert body["error"] == "rate_limited"
        assert body["request_id"]
        # A refused request is a client problem, not a broken service.
        assert 'status_class="4xx"' in metrics_text(client)
        assert 'status_class="5xx"' not in metrics_text(client)


def test_the_health_endpoints_are_not_rate_limited(build):
    app, _, _ = build(rate_limit="1/minute")
    with TestClient(app) as client:
        codes = [client.get("/health/ready").status_code for _ in range(5)]

        assert codes == [200] * 5
        assert client.get("/info").status_code == 200
        assert client.get("/metrics").status_code == 200


def test_a_model_with_a_wrong_checksum_is_never_loaded(build, log_reader, saved_model_sha256):
    app, source, loader = build()
    source.tags = {**source.tags, "model_sha256": WRONG_SHA256}

    with TestClient(app) as client:
        ready = client.get("/health/ready")

        assert ready.status_code == 503
        assert ready.json() == {
            "status": "not_ready",
            "model_version": None,
            "reason": "checksum_mismatch",
        }
        # The pickle was never opened: that is the point of the check.
        assert loader.calls == 0
        assert client.get("/info").json()["status"] == "not_ready"

        line = log_reader.last("checksum_mismatch")
        assert line["level"] == "error"
        assert line["expected"] == WRONG_SHA256
        assert line["actual"] == saved_model_sha256
        assert 'inference_model_load_failures_total{reason="checksum_mismatch"}' in metrics_text(
            client
        )


def test_predictions_are_refused_with_503_while_no_model_is_loaded(build):
    app, source, _ = build()
    source.resolve_error = RuntimeError("mlflow is down")

    with TestClient(app) as client:
        response = client.post("/predict", json=VALID_REQUEST)

        assert response.status_code == 503
        assert response.json()["error"] == "model_not_ready"
        assert client.get("/health/ready").json()["reason"] == "resolve_failed"


def test_a_new_version_behind_the_alias_is_picked_up_while_the_service_runs(build):
    app, source, _ = build(reload_seconds=0.05)

    with TestClient(app) as client:
        assert client.post("/predict", json=VALID_REQUEST).json()["model_version"] == "1"
        source.publish("2")

        deadline = time.monotonic() + 10
        while client.get("/info").json()["model_version"] != "2":
            assert time.monotonic() < deadline, "the alias was not picked up"
            time.sleep(0.05)

        assert client.post("/predict", json=VALID_REQUEST).json()["model_version"] == "2"


def test_the_metrics_carry_the_model_version(client, saved_model_sha256):
    client.post("/predict", json=VALID_REQUEST)
    client.post("/predict", json={**VALID_REQUEST, "MedInc": 99.0})

    body = metrics_text(client)
    assert 'inference_requests_total{model_version="1",status_class="2xx"} 1.0' in body
    assert 'inference_requests_total{model_version="1",status_class="4xx"} 1.0' in body
    assert 'inference_predictions_total{model_version="1"} 1.0' in body
    assert 'inference_prediction_value_count{model_version="1"} 1.0' in body
    assert 'inference_request_duration_seconds_count{model_version="1"} 2.0' in body
    # Prometheus writes the labels in alphabetical order.
    assert (
        'inference_model_info{model_name="california-housing",'
        f'model_sha256="{saved_model_sha256}",model_version="1"}} 1.0' in body
    )
    # The standard HTTP metrics of the instrumentator are there as well.
    assert "http_request_duration_seconds_bucket" in body


def test_probes_and_scrapes_are_not_counted_as_traffic(client):
    client.get("/health/ready")
    client.get("/health/live")

    # The metric exists, but it has no sample yet.
    assert "inference_requests_total{" not in metrics_text(client)


def test_the_request_and_the_prediction_are_two_json_log_events(client, log_reader):
    response = client.post("/predict", json=VALID_REQUEST, headers={"X-Request-ID": "trace-7"})

    request_line = log_reader.last("request")
    assert request_line["method"] == "POST"
    assert request_line["path"] == "/predict"
    assert request_line["status"] == 200
    assert request_line["request_id"] == "trace-7"
    assert request_line["model_version"] == "1"
    assert request_line["latency_ms"] >= 0

    prediction_line = log_reader.last("prediction")
    assert prediction_line["request_id"] == "trace-7"
    assert prediction_line["model_version"] == "1"
    assert prediction_line["prediction"] == response.json()["prediction"]
    # The drift job reads these features back out of Loki.
    assert list(prediction_line["features"]) == FEATURE_COLUMNS
    assert prediction_line["features"]["MedInc"] == VALID_REQUEST["MedInc"]


def test_the_startup_and_the_model_are_logged(client, log_reader, saved_model_sha256):
    startup = log_reader.last("startup")
    assert startup["model_name"] == "california-housing"
    assert startup["model_source"] == "alias staging"

    loaded = log_reader.last("model_loaded")
    assert loaded["model_version"] == "1"
    assert loaded["model_sha256"] == saved_model_sha256
    assert loaded["git_sha"] == GIT_SHA
    assert loaded["run_id"] == RUN_ID


def test_the_fault_switch_answers_with_a_plain_500(build, log_reader):
    app, _, _ = build(fault_rate=1.0)

    with TestClient(app) as client:
        response = client.post("/predict", json=VALID_REQUEST)

        assert response.status_code == 500
        assert response.json() == {
            "error": "internal_error",
            "detail": "the request could not be processed",
            "request_id": response.headers["X-Request-ID"],
        }
        assert log_reader.last("fault_injected")["model_version"] == "1"
        assert 'status_class="5xx"' in metrics_text(client)


def test_a_broken_model_gives_a_500_without_any_details(build, log_reader):
    class BrokenModel:
        def predict(self, frame):
            raise RuntimeError("the secret path is /var/run/secrets/token")

    app, _, _ = build()
    with TestClient(app, raise_server_exceptions=False) as client:
        store = app.state.store
        store._current = replace(store.current, model=BrokenModel())

        response = client.post("/predict", json=VALID_REQUEST)

        assert response.status_code == 500
        assert response.json()["error"] == "internal_error"
        assert "secret" not in response.text
        # The traceback is in the log, where only we can read it.
        assert "the secret path" in log_reader.last("internal_error")["traceback"]
