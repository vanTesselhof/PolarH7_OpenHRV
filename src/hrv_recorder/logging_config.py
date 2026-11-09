"""Application logging to a local rotating file plus stderr."""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path


def configure_logging() -> None:
    log_dir = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "hrv-recorder"
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            log_dir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        ))
    except OSError:
        # A read-only home directory should not prevent the application from starting.
        pass
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=handlers)
