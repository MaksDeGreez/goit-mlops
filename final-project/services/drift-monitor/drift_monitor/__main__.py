"""Entry point, so the job can be started as `python -m drift_monitor`."""

from __future__ import annotations

import sys

from drift_monitor.run import main

if __name__ == "__main__":
    sys.exit(main())
