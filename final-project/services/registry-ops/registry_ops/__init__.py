"""Registry operations for the California Housing model.

stdout of this tool is a machine channel: it carries nothing but the audit
lines, one JSON object per line. MLflow writes a few notes of its own to
stdout, so they are switched off here, before anything imports mlflow.
Importing any module of this package runs this file first.
"""

from __future__ import annotations

import os

# MLflow prints links to runs and experiments to stdout. That would break the
# audit contract, so only the log on stderr keeps them.
os.environ.setdefault("MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT", "true")

# A hint about a feature this project does not use, printed on every import.
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
