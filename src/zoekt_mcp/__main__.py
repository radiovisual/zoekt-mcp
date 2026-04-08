"""Console entry point for ``zoekt-mcp``.

Parses config, builds a FastMCP server, and runs it over stdio so that
MCP clients (Claude Code, Claude Desktop, Cursor, MCP Inspector) can
spawn it as a subprocess.
"""

from __future__ import annotations

import sys

from .config import load_config
from .server import build_server


def main(argv: list[str] | None = None) -> int:
    config = load_config(argv if argv is not None else sys.argv[1:])
    server = build_server(config)
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
