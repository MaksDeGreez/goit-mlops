"""Tests for downloading, checking and swapping the model."""

from __future__ import annotations

import math
import tempfile

import pandas as pd
import pytest
from conftest import GIT_SHA, RUN_ID, VALID_REQUEST, CountingLoader, FakeSource

from inference.config import Settings
from inference.model_store import ModelLoadError, ModelStore, load_sklearn_model

OTHER_SHA256 = "a" * 64


@pytest.fixture
def source(saved_model_dir, saved_model_sha256) -> FakeSource:
    return FakeSource(saved_model_dir, saved_model_sha256)


@pytest.fixture
def loader() -> CountingLoader:
    return CountingLoader(load_sklearn_model)


def build_store(source: FakeSource, loader: CountingLoader, **settings) -> ModelStore:
    return ModelStore(Settings(**settings), source, loader)


def test_a_new_store_has_no_model_yet(source, loader):
    assert build_store(source, loader).current is None


def test_the_model_is_downloaded_checked_and_loaded(source, loader, saved_model_sha256):
    store = build_store(source, loader)

    loaded = store.refresh()

    assert loaded is store.current
    assert loaded.version == "1"
    assert loaded.model_sha256 == saved_model_sha256
    assert loaded.git_sha == GIT_SHA
    assert loaded.run_id == RUN_ID
    assert loaded.loaded_at.endswith("Z")
    assert loader.calls == 1


def test_the_loaded_model_can_predict(source, loader):
    store = build_store(source, loader)
    store.refresh()

    prediction = store.current.model.predict(pd.DataFrame([VALID_REQUEST]))

    assert prediction.shape == (1,)
    assert math.isfinite(float(prediction[0]))


def test_nothing_happens_when_the_alias_still_points_at_the_same_version(source, loader):
    store = build_store(source, loader)
    first = store.refresh()

    assert store.refresh() is None
    assert store.current is first
    assert loader.calls == 1


def test_a_new_version_behind_the_alias_replaces_the_model(source, loader):
    store = build_store(source, loader)
    first = store.refresh()
    source.publish("2")

    second = store.refresh()

    assert second is not None
    assert second.version == "2"
    assert store.current is second
    assert loader.calls == 2
    # The folder of the old model is cleaned up after the swap.
    assert not first.local_dir.exists()


def test_a_pinned_version_is_loaded_and_never_checked_again(source, loader):
    store = build_store(source, loader, model_version="1", model_alias=None)
    store.refresh()
    source.publish("2")

    assert store.refresh() is None
    assert store.current.version == "1"
    assert loader.calls == 1


def test_a_wrong_checksum_stops_the_load_before_the_model_is_opened(
    source, loader, saved_model_sha256
):
    """The whole point of the check: a changed pickle is never executed."""
    source.tags = {**source.tags, "model_sha256": OTHER_SHA256}
    store = build_store(source, loader)

    with pytest.raises(ModelLoadError) as error:
        store.refresh()

    assert error.value.reason == "checksum_mismatch"
    assert error.value.details["expected"] == OTHER_SHA256
    assert error.value.details["actual"] == saved_model_sha256
    assert loader.calls == 0
    assert store.current is None


def test_the_pinned_checksum_from_git_has_to_match_as_well(source, loader):
    store = build_store(source, loader, model_sha256=OTHER_SHA256)

    with pytest.raises(ModelLoadError) as error:
        store.refresh()

    assert error.value.reason == "checksum_mismatch"
    assert error.value.details["pinned"] == OTHER_SHA256
    assert loader.calls == 0


def test_a_version_without_the_checksum_tag_is_refused(source, loader):
    source.tags = {"git_sha": GIT_SHA}
    store = build_store(source, loader)

    with pytest.raises(ModelLoadError) as error:
        store.refresh()

    assert error.value.reason == "missing_checksum_tag"
    assert loader.calls == 0


def test_a_registry_that_cannot_be_read_gives_a_clear_reason(source, loader):
    source.resolve_error = RuntimeError("connection refused")
    store = build_store(source, loader)

    with pytest.raises(ModelLoadError) as error:
        store.refresh()

    assert error.value.reason == "resolve_failed"


def test_a_failed_download_gives_a_clear_reason(source, loader):
    source.download_error = OSError("no route to host")
    store = build_store(source, loader)

    with pytest.raises(ModelLoadError) as error:
        store.refresh()

    assert error.value.reason == "download_failed"


def test_a_broken_model_file_gives_a_clear_reason(source, loader, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "MLmodel").write_text("flavors:\n  sklearn:\n    pickled_model: model.pkl\n")
    (empty / "model.pkl").write_bytes(b"")
    source.model_dir = empty
    store = build_store(source, loader)

    with pytest.raises(ModelLoadError) as error:
        store.refresh()

    assert error.value.reason == "bad_artifact"
    assert loader.calls == 0


def test_the_model_in_use_survives_a_failing_refresh(source, loader):
    store = build_store(source, loader)
    first = store.refresh()
    source.publish("2")
    source.download_error = OSError("no route to host")

    with pytest.raises(ModelLoadError):
        store.refresh()

    assert store.current is first
    assert first.local_dir.exists()


def test_a_failed_load_leaves_no_temporary_folder_behind(source, loader, tmp_path, monkeypatch):
    """A pod that keeps retrying must not fill its disk with dead downloads."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    source.tags = {**source.tags, "model_sha256": OTHER_SHA256}
    store = build_store(source, loader)

    with pytest.raises(ModelLoadError):
        store.refresh()

    assert source.download_calls == 1
    assert list(tmp_path.iterdir()) == []


def test_close_removes_the_downloaded_files(source, loader):
    store = build_store(source, loader)
    loaded = store.refresh()

    store.close()

    assert store.current is None
    assert not loaded.local_dir.exists()
