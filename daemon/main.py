"""ContextWeave daemon entry point.

Loads configuration and starts the Uvicorn ASGI server.
Handles port-already-in-use with a clear message and exit code 1.
"""

from __future__ import annotations

import sys

import structlog
import uvicorn

from contextweave.config import load_config

log: structlog.stdlib.BoundLogger = structlog.get_logger()


def main() -> None:
    """Start the ContextWeave daemon."""
    config = load_config()

    try:
        uvicorn.run(
            "contextweave.server:app",
            host=config.daemon.host,
            port=config.daemon.port,
            log_config=None,
        )
    except OSError as exc:
        if "address already in use" in str(exc).lower() or "error while attempting to bind" in str(exc).lower():
            log.error(
                "port_in_use",
                port=config.daemon.port,
                hint=f"Port {config.daemon.port} is already in use. "
                     f"Is another ContextWeave daemon running?",
            )
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
