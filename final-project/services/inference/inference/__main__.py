"""Start the service: `python -m inference`."""

from __future__ import annotations

import uvicorn

from inference.app import create_app
from inference.config import Settings
from inference.logging_setup import configure_logging


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",  # noqa: S104 - inside a pod this is the only useful value
        port=settings.port,
        # Our own logging is already set up, and uvicorn would replace it.
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
