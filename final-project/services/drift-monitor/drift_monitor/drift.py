"""The drift check itself, with Evidently.

Only the eight feature columns are compared. The reference file also has the
target `MedHouseVal`, but live there is no target: there is a prediction, and a
prediction is not the same thing as a real house price. Comparing the two would
report drift that does not exist, so the target column is dropped and the job
answers one clear question: does the traffic still look like the training data?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from evidently import DataDefinition, Dataset, Report
from evidently.presets import DataDriftPreset

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

# PSI is a distance between two distributions, so a high value means drift.
# The default score of the preset is a p-value, where a low value means drift,
# and the two read in opposite directions. The method is pinned so a dashboard
# never has to guess which one it is looking at.
DRIFT_METHOD = "psi"

DRIFTED_COUNT_METRIC = "DriftedColumnsCount"
COLUMN_METRIC = "ValueDrift"

# The image is built with `final-project/` as the build context.
CONTAINER_REFERENCE_PATH = Path("/app/data/reference.csv")
# services/drift-monitor/drift_monitor/drift.py -> final-project/data/
REPO_REFERENCE_PATH = Path(__file__).resolve().parents[3] / "data" / "reference.csv"


@dataclass
class DriftResult:
    """What one drift check found."""

    samples: int
    drifted_columns: int
    drifted_share: float
    scores: dict[str, float] = field(default_factory=dict)
    threshold: float = 0.0

    def drifted_column_names(self) -> list[str]:
        return sorted(name for name, score in self.scores.items() if score >= self.threshold)


def default_reference_path() -> Path:
    """Where to look for the reference sample when nothing is set."""
    for candidate in (CONTAINER_REFERENCE_PATH, REPO_REFERENCE_PATH):
        if candidate.is_file():
            return candidate
    return CONTAINER_REFERENCE_PATH


def load_features(path: str | Path, columns: list[str] | None = None) -> pd.DataFrame:
    """Read a CSV and keep the feature columns only."""
    wanted = columns or FEATURE_COLUMNS
    csv_path = Path(path)
    if not csv_path.is_file():
        raise FileNotFoundError(f"file not found: {csv_path}")

    frame = pd.read_csv(csv_path)
    missing = [column for column in wanted if column not in frame.columns]
    if missing:
        raise ValueError(f"these columns are missing in {csv_path}: {missing}")
    return frame[wanted].apply(pd.to_numeric, errors="coerce").dropna().reset_index(drop=True)


def _as_dataset(frame: pd.DataFrame, columns: list[str]) -> Dataset:
    definition = DataDefinition(numerical_columns=list(columns))
    return Dataset.from_pandas(frame, data_definition=definition)


def run_report(
    current: pd.DataFrame,
    reference: pd.DataFrame,
    columns: list[str] | None = None,
):
    """Run the Evidently report. Current data first, reference second."""
    wanted = columns or FEATURE_COLUMNS
    report = Report([DataDriftPreset(method=DRIFT_METHOD)])
    return report.run(_as_dataset(current, wanted), _as_dataset(reference, wanted))


def read_result(report_result, samples: int) -> DriftResult:
    """Pull the numbers out of the report.

    The metric entries are matched on `config.type`, because the metric name
    also carries the settings and would change with them.
    """
    result = DriftResult(samples=samples, drifted_columns=0, drifted_share=0.0)
    for metric in report_result.dict().get("metrics", []):
        config = metric.get("config", {})
        kind = str(config.get("type", "")).split(":")[-1]
        value = metric.get("value")
        if kind == DRIFTED_COUNT_METRIC:
            result.drifted_columns = int(value["count"])
            result.drifted_share = float(value["share"])
        elif kind == COLUMN_METRIC:
            result.scores[str(config["column"])] = float(value)
            result.threshold = float(config.get("threshold", result.threshold))
    return result


def check_drift(
    current: pd.DataFrame,
    reference: pd.DataFrame,
    columns: list[str] | None = None,
    report_path: str | Path | None = None,
) -> DriftResult:
    """Compare live features with the reference sample."""
    report_result = run_report(current, reference, columns)
    if report_path is not None:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        report_result.save_html(str(report_path))
    return read_result(report_result, samples=len(current))
