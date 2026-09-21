"""Data drift job for the California Housing model.

Evidently sends usage statistics home when it is imported. This is a batch job
in a private cluster, so the switch is set here, before anything imports
evidently: importing any module of this package runs this file first.
"""

from __future__ import annotations

import os

os.environ.setdefault("DO_NOT_TRACK", "1")
