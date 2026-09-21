"""The drift check: shifted data is found, unchanged data is not."""

from __future__ import annotations

import pathlib

import pytest

from drift_monitor.drift import (
    FEATURE_COLUMNS,
    check_drift,
    default_reference_path,
    load_features,
    repo_file,
)


@pytest.fixture(scope="session")
def quiet(same_as_reference, reference):
    """The result for data that did not change."""
    return check_drift(same_as_reference, reference)


@pytest.fixture(scope="session")
def noisy(shifted, reference):
    """The result for data with three features moved."""
    return check_drift(shifted, reference)


def test_data_taken_from_the_reference_does_not_drift(quiet, same_as_reference):
    assert quiet.samples == len(same_as_reference)
    assert quiet.drifted_columns == 0
    assert quiet.drifted_share == 0.0
    assert quiet.drifted_column_names() == []


def test_every_column_has_a_score_below_the_threshold(quiet):
    assert set(quiet.scores) == set(FEATURE_COLUMNS)
    assert quiet.threshold == pytest.approx(0.1)
    assert max(quiet.scores.values()) < quiet.threshold


def test_shifted_features_are_reported_as_drift(noisy):
    assert noisy.drifted_columns == 3
    assert noisy.drifted_share == pytest.approx(3 / 8)
    assert noisy.drifted_column_names() == ["AveRooms", "MedInc", "Population"]


def test_the_psi_score_is_a_distance_so_drift_makes_it_large(noisy):
    assert noisy.scores["MedInc"] > 1.0
    assert noisy.scores["Latitude"] < 0.1


def test_the_html_report_is_written_when_a_path_is_given(same_as_reference, reference, tmp_path):
    path = tmp_path / "reports" / "drift.html"
    check_drift(same_as_reference, reference, report_path=path)

    assert path.is_file()
    assert path.stat().st_size > 1000


def test_the_reference_file_is_found_in_the_repository():
    path = default_reference_path()

    assert path.is_file()
    assert path.name == "reference.csv"


def test_repo_file_walks_four_folders_up():
    path = repo_file("/repo/final-project/services/drift-monitor/drift_monitor/drift.py", "data")

    assert path == pathlib.Path("/repo/final-project/data")


def test_repo_file_survives_a_package_close_to_the_root():
    """Inside the image the package is /app/drift_monitor, so there is no
    fourth parent. The path is then wrong and unused, but it must not raise:
    it is computed while the module is imported."""
    assert repo_file("/app/drift_monitor/drift.py", "data") == pathlib.Path("/data")


def test_loading_a_csv_keeps_only_the_feature_columns():
    frame = load_features(default_reference_path())

    assert list(frame.columns) == FEATURE_COLUMNS
    assert len(frame) == 2500


def test_a_missing_file_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_features(tmp_path / "nothing.csv")


def test_a_csv_without_the_features_is_an_error(tmp_path):
    path = tmp_path / "wrong.csv"
    path.write_text("a,b\n1,2\n")

    with pytest.raises(ValueError, match="missing"):
        load_features(path)
