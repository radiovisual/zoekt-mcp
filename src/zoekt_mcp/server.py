"""FastMCP server wiring for zoekt-mcp.

This module exposes :func:`build_server`, a factory that returns a
configured :class:`mcp.server.fastmcp.FastMCP` instance bound to a
:class:`ZoektClient`. Tool implementations are attached in a follow-up
commit; for now this file is just the plumbing that lets
``__main__.py`` spin up a server and run it over stdio.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .client import ZoektClient
from .config import ZoektConfig

SERVER_NAME = "zoekt-mcp"
SERVER_INSTRUCTIONS = (
    "Run indexed code search over the user's codebase using Sourcegraph "
    "Zoekt. Supports a rich query language: `repo:`, `file:`, `lang:`, "
    "`sym:`, `case:yes`, boolean AND (space) / OR, and `/regex/` patterns. "
    "Use `list_repos` first if you don't know what's indexed, then "
    "`search_code` to find matches, and `get_file` to pull full file "
    "contents when you need more context than the search snippet."
)


def build_server(config: ZoektConfig) -> FastMCP:
    """Create a FastMCP server configured against ``config``.

    The returned server owns a :class:`ZoektClient`; callers should run
    it via ``server.run(transport="stdio")`` and let process exit close
    the underlying HTTP client.
    """
    client = ZoektClient(config.backend_url, timeout=config.timeout)
    mcp = FastMCP(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)
    # Store the client on the server so tool registration (added in the
    # next commit) can reach it without leaking module-level state.
    mcp._zoekt_client = client  # type: ignore[attr-defined]
    return mcp
