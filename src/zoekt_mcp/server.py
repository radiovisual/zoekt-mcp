"""FastMCP server wiring for zoekt-mcp.

Exposes :func:`build_server`, a factory that returns a configured
:class:`mcp.server.fastmcp.FastMCP` instance bound to a
:class:`ZoektClient` and with three tools registered:

* ``search_code`` — run a zoekt query, return compact match records.
* ``list_repos``  — enumerate indexed repositories.
* ``get_file``    — fetch raw file contents from an indexed repo.
"""

from __future__ import annotations

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
# zoekt's JSON responses are verbose and use multiple casings across
# versions (``FileName`` vs ``fileName``, ``Repository`` vs ``repo``). We
# trim responses down to the fields an agent actually cares about and
# handle both casings via :func:`_pick`.


def _pick(obj: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Return the first value found under any of ``keys`` in ``obj``."""
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
    return default


def _shape_search_result(query: str, raw: dict[str, Any]) -> dict[str, Any]:
    stats = raw.get("Stats") or raw.get("stats") or {}
    files_raw = raw.get("Files") or raw.get("files") or []

    files: list[dict[str, Any]] = []
    for f in files_raw:
        files.append(
            {
                "repo": _pick(f, "Repository", "Repo", "repo", default=""),
                "file": _pick(f, "FileName", "fileName", default=""),
                "language": _pick(f, "Language", "language", default=""),
                "branches": _pick(f, "Branches", "branches", default=[]) or [],
                "score": _pick(f, "Score", "score"),
                "matches": [_shape_match(m) for m in _iter_matches(f)],
            }
        )

    return {
        "query": query,
        "file_count": _pick(stats, "FileCount", "fileCount"),
        "match_count": _pick(stats, "MatchCount", "matchCount"),
        "duration_ms": _pick(stats, "Duration", "duration"),
        "files": files,
    }


def _iter_matches(file_entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull a file's match list regardless of whether zoekt used line- or
    chunk-match mode.
    """
    for key in ("LineMatches", "lineMatches", "ChunkMatches", "chunkMatches", "Matches", "matches"):
        matches = file_entry.get(key)
        if matches:
            return matches
    return []


def _shape_match(m: dict[str, Any]) -> dict[str, Any]:
    line_number = _pick(m, "LineNumber", "lineNum", "Line", "line")
    line_text = _pick(m, "LineContent", "Line", "line", "lineContent", default="")
    # Fragments are zoekt's highlighted match segments; concat into a
    # single snippet the agent can read.
    fragments = _pick(m, "Fragments", "fragments", default=[]) or []
    snippet = "".join(
        f"{frag.get('pre', '')}{frag.get('match', '')}{frag.get('post', '')}"
        for frag in fragments
    )
    return {
        "line": line_number,
        "text": line_text if isinstance(line_text, str) else str(line_text),
        "snippet": snippet or None,
        "before": _pick(m, "Before", "before"),
        "after": _pick(m, "After", "after"),
    }


def _shape_list_result(raw: dict[str, Any]) -> dict[str, Any]:
    repos_raw = raw.get("Repos") or raw.get("repos") or raw.get("List") or []
    repos: list[dict[str, Any]] = []
    for entry in repos_raw:
        # zoekt nests details under "Repository" in the List response.
        repo = entry.get("Repository") or entry.get("repository") or entry
        repos.append(
            {
                "name": _pick(repo, "Name", "name", default=""),
                "url": _pick(repo, "URL", "Url", "url", default=""),
                "branches": [
                    _pick(b, "Name", "name") for b in (_pick(repo, "Branches", "branches", default=[]) or [])
                ],
                "index_time": _pick(entry, "IndexMetadata", "indexMetadata"),
            }
        )
    return {"count": len(repos), "repos": repos}
