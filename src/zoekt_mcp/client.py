"""Async HTTP client for a zoekt-webserver backend.

Thin wrapper around the three zoekt-webserver endpoints we need:

* ``POST /api/search`` — run a zoekt query (requires the server to have
  been started with ``-rpc``, which registers the JSON API under
  ``/api/*``; without it, requests fall through to the HTML handlers).
* ``POST /api/list``   — enumerate indexed repositories (same gate).
* ``GET  /print?format=raw`` — fetch a file's raw contents as
  ``text/plain``.

The client is intentionally dumb: it does not interpret query syntax and does
not post-process match results beyond returning the JSON body. Response
shaping for the MCP tool surface lives in :mod:`zoekt_mcp.server`.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self

import httpx

DEFAULT_BACKEND_URL = "http://localhost:6070"
DEFAULT_TIMEOUT_SECONDS = 30.0


class ZoektBackendError(RuntimeError):
    """Raised when zoekt-webserver returns a non-2xx response or invalid JSON.

    The ``body`` attribute holds the raw response body (truncated) so callers
    can surface a useful message to the agent rather than a bare stack trace.
    """

    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class ZoektClient:
    """Async client for a zoekt-webserver instance.

    Use as an async context manager so the underlying ``httpx.AsyncClient``
    is closed deterministically::

        async with ZoektClient("http://localhost:6070") as client:
            result = await client.search("lang:python def hello")
    """

    def __init__(
        self,
        backend_url: str = DEFAULT_BACKEND_URL,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.backend_url = backend_url.rstrip("/")
        self._timeout = timeout
        # Allow injecting a pre-built client for tests (respx, etc.).
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def search(
        self,
        query: str,
        *,
        num_context_lines: int = 3,
        max_doc_display_count: int = 50,
        chunk_matches: bool = True,
        extra_opts: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a zoekt query. Returns the ``Result`` sub-object.

        ``query`` is a raw zoekt query string (e.g. ``"lang:python def hello"``).
        The caller is responsible for escaping/quoting where necessary.
        """
        opts: dict[str, Any] = {
            "NumContextLines": num_context_lines,
            "MaxDocDisplayCount": max_doc_display_count,
            "ChunkMatches": chunk_matches,
        }
        if extra_opts:
            opts.update(extra_opts)

        payload = {"Q": query, "Opts": opts}
        data = await self._post_json("/api/search", payload)
        # zoekt wraps the search result under a top-level "Result" key.
        return data.get("Result", data)

    async def list_repos(self, query: str = "repo:.") -> dict[str, Any]:
        """List indexed repositories matching ``query``.

        Per zoekt's JSON API, the query for ``/api/list`` must contain only
        ``repo:`` atoms; the default ``"repo:."`` means "every repo".
        """
        payload = {"Q": query}
        data = await self._post_json("/api/list", payload)
        return data.get("List", data)

    async def get_file(self, repo: str, path: str, branch: str = "HEAD") -> str:
        """Fetch raw file contents via ``/print?format=raw``.

        Returns the file body as a plain string. Raises
        :class:`ZoektBackendError` on any non-2xx response so the tool
        layer can surface a useful message to the agent.
        """
        params = {"r": repo, "f": path, "b": branch, "format": "raw"}
        try:
            response = await self._http.get(f"{self.backend_url}/print", params=params)
        except httpx.HTTPError as exc:
            raise ZoektBackendError(f"GET /print failed: {exc}") from exc

        if response.status_code >= 400:
            raise ZoektBackendError(
                f"GET /print returned {response.status_code}",
                status_code=response.status_code,
                body=_truncate(response.text),
            )

        return response.text

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.backend_url}{path}"
        try:
            response = await self._http.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise ZoektBackendError(f"POST {path} failed: {exc}") from exc

        if response.status_code >= 400:
            raise ZoektBackendError(
                f"POST {path} returned {response.status_code}",
                status_code=response.status_code,
                body=_truncate(response.text),
            )

        try:
            return response.json()
        except ValueError as exc:
            raise ZoektBackendError(
                f"POST {path} returned invalid JSON",
                status_code=response.status_code,
                body=_truncate(response.text),
            ) from exc


def _truncate(text: str, limit: int = 500) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [truncated {len(text) - limit} chars]"
