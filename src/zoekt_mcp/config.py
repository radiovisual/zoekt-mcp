"""Runtime configuration for the zoekt-mcp server.

Config comes from (in order of precedence):

1. Command-line flags (``--backend``, ``--timeout``).
2. Environment variables (``ZOEKT_URL``, ``ZOEKT_TIMEOUT``).
3. Hard-coded defaults.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

from .client import DEFAULT_BACKEND_URL, DEFAULT_TIMEOUT_SECONDS


@dataclass(frozen=True)
class ZoektConfig:
    backend_url: str
    timeout: float


def load_config(argv: list[str] | None = None) -> ZoektConfig:
    """Parse CLI flags and environment variables into a :class:`ZoektConfig`."""
    parser = argparse.ArgumentParser(
        prog="zoekt-mcp",
        description="MCP server exposing Sourcegraph Zoekt code search.",
    )
    parser.add_argument(
        "--backend",
        default=os.environ.get("ZOEKT_URL", DEFAULT_BACKEND_URL),
        help=(
            "Base URL of a running zoekt-webserver. "
            "Defaults to $ZOEKT_URL or http://localhost:6070."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("ZOEKT_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)),
        help="HTTP timeout in seconds for requests to zoekt-webserver.",
    )

    args = parser.parse_args(argv)
    return ZoektConfig(backend_url=args.backend, timeout=args.timeout)
