"""Entry point, so the tool can be started as `python -m registry_ops`."""

from __future__ import annotations

import sys

from registry_ops.cli import main

if __name__ == "__main__":
    sys.exit(main())
