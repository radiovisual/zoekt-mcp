"""FastMCP server wiring for zoekt-mcp.

Exposes :func:`build_server`, a factory that returns a configured
:class:`mcp.server.fastmcp.FastMCP` instance bound to a
:class:`ZoektClient` and with three tools registered:

* ``search_code`` — run a zoekt query, return compact match records.
* ``list_repos``  — enumerate indexed repositories.
* ``get_file``    — fetch raw file contents from an indexed repo.
"""

from __future__ import annotations

import base64
from typing import Any

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

# Default caps on how much data we hand back to the LLM. These protect the
# agent's context window from being blown out by a wide query.
DEFAULT_MAX_RESULTS = 50
MAX_RESULTS_CEILING = 500
DEFAULT_CONTEXT_LINES = 3
CONTEXT_LINES_CEILING = 20


def build_server(config: ZoektConfig) -> FastMCP:
    """Create a FastMCP server configured against ``config``.

    The returned server owns a :class:`ZoektClient`. Callers should run
    it via ``server.run(transport="stdio")`` and let process exit close
    the underlying HTTP client.
    """
    client = ZoektClient(config.backend_url, timeout=config.timeout)
    mcp = FastMCP(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)
    _register_tools(mcp, client)
    mcp._zoekt_client = client  # type: ignore[attr-defined]
    return mcp


def _register_tools(mcp: FastMCP, client: ZoektClient) -> None:
    @mcp.tool()
    async def search_code(
        query: str,
        max_results: int = DEFAULT_MAX_RESULTS,
        context_lines: int = DEFAULT_CONTEXT_LINES,
    ) -> dict[str, Any]:
        """Run a Zoekt query against the indexed corpus.

        Query syntax highlights:

        - ``repo:NAME`` restrict to repos whose name matches NAME (regex)
        - ``file:PATH`` restrict to files whose path matches PATH (regex)
        - ``lang:LANGUAGE`` restrict to a language (``python``, ``go``, ...)
        - ``sym:IDENT`` match symbol definitions (functions, classes, ...)
        - ``case:yes`` case-sensitive content match
        - ``/regex/`` regex content match (literal match by default)
        - whitespace is AND; use ``or`` for boolean OR

        Examples:

        - ``lang:python def hello`` — Python files containing ``def hello``
        - ``sym:users`` — anything that defines a ``users`` symbol
        - ``repo:flask-app file:app.py`` — within one file of one repo

        Returns a compact object with ``files`` (each containing ``repo``,
        ``file``, ``language``, and ``matches``) plus top-level stats.
        Results are capped at ``max_results`` files.
        """
        capped_max = max(1, min(max_results, MAX_RESULTS_CEILING))
        capped_ctx = max(0, min(context_lines, CONTEXT_LINES_CEILING))
        raw = await client.search(
            query,
            num_context_lines=capped_ctx,
            max_doc_display_count=capped_max,
        )
        return _shape_search_result(query, raw)

    @mcp.tool()
    async def list_repos(filter: str = "") -> dict[str, Any]:
        """List indexed repositories.

        ``filter`` is an optional ``repo:`` atom (e.g. ``repo:flask`` or
        ``repo:.`` for all) used to narrow the list. Leave empty to list
        every indexed repository.

        Returns ``{"repos": [{name, url, branches, ...}, ...], "count": N}``.
        """
        query = filter.strip() or "repo:."
        if not query.startswith("repo:") and "repo:" not in query:
            query = f"repo:{query}"
        raw = await client.list_repos(query)
        return _shape_list_result(raw)

    @mcp.tool()
    async def get_file(repo: str, path: str, branch: str = "HEAD") -> dict[str, Any]:
        """Fetch the full contents of a file from an indexed repository.

        ``repo`` is the repository name as reported by ``list_repos``;
        ``path`` is the file path within that repo; ``branch`` defaults
        to ``HEAD`` but can be any branch zoekt has indexed. Returns
        ``{"repo", "path", "branch", "content"}``.
        """
        content = await client.get_file(repo=repo, path=path, branch=branch)
        return {
            "repo": repo,
            "path": path,
            "branch": branch,
            "content": content,
        }


# ---------------------------------------------------------------------- #
# Response shaping helpers
# ---------------------------------------------------------------------- #
#
# zoekt's JSON responses are verbose. We trim them down to the fields
# an agent actually cares about. Shapes below match the real output
# from `zoekt-webserver -rpc` (tested against sourcegraph/zoekt-webserver
# image, index format v16):
#
#   /api/search → {"Result": {FileCount, MatchCount, Duration, Files:
#                    [{FileName, Repository, Language, Branches, Score,
#                      ChunkMatches or LineMatches: [...]}]}}
#
#     - ChunkMatches (what you get when Opts.ChunkMatches=true, which
#       is the client default) contain multi-line context blocks:
#         {Content (base64), ContentStart {LineNumber, Column},
#          Ranges: [{Start, End}], SymbolInfo: [{Sym, Kind, ...}],
#          BestLineMatch, Score}
#
#     - LineMatches (the legacy format) are single lines:
#         {LineNumber, Line (base64), LineStart, LineEnd,
#          LineFragments: [{LineOffset, MatchLength, SymbolInfo}]}
#
#   /api/list   → {"List": {Repos: [{Repository: {Name, URL, Source,
#                    Branches: [{Name, Version}]}, IndexMetadata:
#                    {IndexTime, ...}, Stats: {...}}], Stats: {...}}}


def _shape_search_result(query: str, raw: dict[str, Any]) -> dict[str, Any]:
    files_raw = raw.get("Files") or []

    files: list[dict[str, Any]] = []
    for f in files_raw:
        files.append(
            {
                "repo": f.get("Repository", ""),
                "file": f.get("FileName", ""),
                "language": f.get("Language", ""),
                "branches": f.get("Branches") or [],
                "score": f.get("Score"),
                "matches": _shape_file_matches(f),
            }
        )

    return {
        "query": query,
        "file_count": raw.get("FileCount"),
        "match_count": raw.get("MatchCount"),
        # zoekt reports Duration in nanoseconds.
        "duration_ns": raw.get("Duration"),
        "files": files,
    }


def _shape_file_matches(file_entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Pick whichever match format the response uses and shape it.

    Prefers ``ChunkMatches`` (richer, multi-line context) and falls
    back to ``LineMatches`` (one line each) when only the legacy
    format is present.
    """
    chunk_matches = file_entry.get("ChunkMatches") or []
    if chunk_matches:
        return [_shape_chunk_match(cm) for cm in chunk_matches]
    return [_shape_line_match(m) for m in file_entry.get("LineMatches") or []]


def _shape_chunk_match(cm: dict[str, Any]) -> dict[str, Any]:
    content = _decode_line(cm.get("Content"))
    content_start = cm.get("ContentStart") or {}
    ranges_raw = cm.get("Ranges") or []
    symbols_raw = cm.get("SymbolInfo") or []
    return {
        "line": cm.get("BestLineMatch") or content_start.get("LineNumber"),
        "start_line": content_start.get("LineNumber"),
        "text": content,
        "ranges": [
            {
                "start_line": (r.get("Start") or {}).get("LineNumber"),
                "start_col": (r.get("Start") or {}).get("Column"),
                "end_line": (r.get("End") or {}).get("LineNumber"),
                "end_col": (r.get("End") or {}).get("Column"),
            }
            for r in ranges_raw
        ],
        "symbols": [
            {
                "name": s.get("Sym"),
                "kind": s.get("Kind"),
                "parent": s.get("Parent") or None,
            }
            for s in symbols_raw
            if s and s.get("Sym")
        ]
        or None,
    }


def _shape_line_match(m: dict[str, Any]) -> dict[str, Any]:
    line_text = _decode_line(m.get("Line"))
    fragments = m.get("LineFragments") or []
    highlights = [
        {
            "line_offset": frag.get("LineOffset"),
            "length": frag.get("MatchLength"),
        }
        for frag in fragments
    ]
    return {
        "line": m.get("LineNumber"),
        "text": line_text,
        "highlights": highlights or None,
        "before": m.get("Before"),
        "after": m.get("After"),
    }


def _decode_line(value: Any) -> str:
    """Zoekt encodes ``Line`` as base64 bytes of the source line.

    Decode defensively: if the value is not a base64 string, fall back
    to ``str(value)`` so we never crash on a surprising response.
    """
    if not isinstance(value, str) or not value:
        return "" if value is None else str(value)
    try:
        return base64.b64decode(value, validate=True).decode("utf-8", errors="replace")
    except (ValueError, OSError):
        return value


def _shape_list_result(raw: dict[str, Any]) -> dict[str, Any]:
    repos_raw = raw.get("Repos") or []
    repos: list[dict[str, Any]] = []
    for entry in repos_raw:
        repo = entry.get("Repository") or {}
        index_meta = entry.get("IndexMetadata") or {}
        branches = [b.get("Name") for b in (repo.get("Branches") or []) if b.get("Name")]
        repos.append(
            {
                "name": repo.get("Name", ""),
                "url": repo.get("URL", ""),
                "source": repo.get("Source", ""),
                "branches": branches,
                "index_time": index_meta.get("IndexTime"),
                "has_symbols": repo.get("HasSymbols"),
            }
        )
    return {"count": len(repos), "repos": repos}
