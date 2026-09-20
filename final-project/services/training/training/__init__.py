"""Training job for the California Housing model.

Two environment settings have to be in place before anything imports mlflow,
so they are set here: importing any module of this package runs this file
first.
"""

from __future__ import annotations

import os

# The MLflow server serves artifacts through its own HTTP endpoint. With
# multipart download enabled the client asks the object store directly with a
# pre-signed URL, which a client outside the cluster cannot reach. The download
# then silently produces a file of the right size filled with spaces, so the
# checksum check would fail for no visible reason. Turning it off keeps every
# download on the tracking URI.
os.environ.setdefault("MLFLOW_ENABLE_PROXY_MULTIPART_DOWNLOAD", "false")

# MLflow prints a hint about a feature this project does not use every time it
# is imported. The job log is read by people, so keep it clean.
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
