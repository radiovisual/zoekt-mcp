"""End-to-end tests against a live zoekt-webserver.

These tests require the ``deploy/docker-compose.yml`` stack to be up
(or any other zoekt-webserver reachable at ``$ZOEKT_URL``, defaulting
to ``http://localhost:6070``). They skip cleanly when the backend is
unreachable so ``pytest`` in a fresh checkout still passes without
Docker.

Bring the stack up first::

    docker compose -f deploy/docker-compose.yml up -d

Then::

    pytest tests/test_integration.py -v

The assertions only touch the examples/ verification corpus, so the
tests are idempotent and do not mutate any state in the backend.
"""

from __future__ import annotations

import os

import httpx
import pytest

from zoekt_mcp.client import DEFAULT_BACKEND_URL, ZoektClient

BACKEND_URL = os.environ.get("ZOEKT_URL", DEFAULT_BACKEND_URL)


def _backend_reachable() -> bool:
    try:
        response = httpx.get(f"{BACKEND_URL}/healthz", timeout=2.0)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


pytestmark = pytest.mark.skipif(
    not _backend_reachable(),
    reason=(
        f"zoekt-webserver at {BACKEND_URL} is not reachable. "
        "Bring the stack up with "
        "`docker compose -f deploy/docker-compose.yml up -d` "
        "or set ZOEKT_URL to an existing backend."
    ),
)


@pytest.fixture
async def client() -> ZoektClient:
    async with ZoektClient(BACKEND_URL) as c:
        yield c


def _all_file_names(result: dict) -> list[str]:
    """Collect file names from a search response regardless of key casing."""
    files = result.get("Files") or result.get("files") or []
    names: list[str] = []
    for f in files:
        name = f.get("FileName") or f.get("fileName") or ""
        if name:
            names.append(name)
    return names


def _all_repo_names(list_result: dict) -> list[str]:
    repos = list_result.get("Repos") or list_result.get("repos") or list_result.get("List") or []
    names: list[str] = []
    for entry in repos:
        repo = entry.get("Repository") or entry.get("repository") or entry
        name = repo.get("Name") or repo.get("name") or ""
        if name:
            names.append(name)
    return names


async def test_list_repos_includes_both_examples(client: ZoektClient) -> None:
    result = await client.list_repos("repo:.")
    names = _all_repo_names(result)

    # Zoekt uses the indexed directory name as the repo name.
    joined = " ".join(names)
    assert "flask-app" in joined, f"flask-app missing from repos: {names}"
    assert "express-app" in joined, f"express-app missing from repos: {names}"


async def test_search_finds_python_hello(client: ZoektClient) -> None:
    result = await client.search("lang:python def hello")
    files = _all_file_names(result)

    assert any("app.py" in f for f in files), f"expected a match in flask-app/app.py, got: {files}"


async def test_search_finds_javascript_users(client: ZoektClient) -> None:
    result = await client.search("lang:javascript USERS")
    files = _all_file_names(result)

    assert any("index.js" in f for f in files), (
        f"expected a match in express-app/index.js, got: {files}"
    )


async def test_get_file_returns_flask_source(client: ZoektClient) -> None:
    content = await client.get_file("flask-app", "app.py")

    assert "def hello" in content
    assert "USERS" in content


# ---------------------------------------------------------------------
# ctags / symbol-search checks.
#
# Zoekt invokes universal-ctags at index time to extract symbol
# definitions (functions, classes, constants, ...). The `sym:` query
# atom *only* matches those ctags-extracted definitions, so a passing
# `sym:` query is end-to-end proof that ctags was present and working
# when the shards were built. These tests exist to catch the silent
# regression where the upstream indexer image stops shipping ctags, or
# someone swaps in a slimmer image without it — at that point indexing
# still succeeds, content search still works, but ranking and symbol
# navigation quietly degrade.
#
# See deploy/README.md ("Symbol search & ctags") for a walkthrough.
# ---------------------------------------------------------------------


async def test_index_has_symbols_flag(client: ZoektClient) -> None:
    """Every example repo should report HasSymbols=true after indexing.

    Zoekt sets this flag on the repo metadata when ctags produced at
    least one symbol for the repo. If it's false, ctags either wasn't
    on $PATH in the indexer image or failed at runtime.
    """
    result = await client.list_repos("repo:.")
    repos = result.get("Repos") or result.get("repos") or result.get("List") or []

    seen: dict[str, bool] = {}
    for entry in repos:
        repo = entry.get("Repository") or entry.get("repository") or entry
        name = repo.get("Name") or repo.get("name") or ""
        has_symbols = repo.get("HasSymbols")
        if has_symbols is None:
            has_symbols = repo.get("hasSymbols")
        if name:
            seen[name] = bool(has_symbols)

    for required in ("flask-app", "express-app"):
        matches = [n for n in seen if required in n]
        assert matches, f"{required} missing from repos: {list(seen)}"
        for name in matches:
            assert seen[name], (
                f"repo {name!r} was indexed without symbol data — "
                "universal-ctags is probably missing from the indexer image. "
                "See deploy/README.md 'Symbol search & ctags'."
            )


async def test_sym_search_finds_python_function(client: ZoektClient) -> None:
    """`sym:hello` must resolve to the Python `def hello():` in flask-app.

    A plain content search for "hello" would also hit docstrings,
    comments, and string literals — `sym:` narrows to ctags definitions
    only, so this assertion fails if ctags wasn't run at index time.
    """
    result = await client.search("sym:hello lang:python")
    files = _all_file_names(result)

    assert any("app.py" in f for f in files), (
        f"sym:hello should resolve to flask-app/app.py via ctags; "
        f"got: {files}. If this is empty, ctags probably didn't run."
    )


async def test_sym_search_cross_language_constant(client: ZoektClient) -> None:
    """`sym:USERS` must find the constant in both Python and JavaScript.

    The examples corpus is deliberately shaped so that `USERS` is
    defined as a module-level constant in both flask-app/app.py and
    express-app/index.js. ctags extracts both, and `sym:USERS` should
    return matches in both files.
    """
    result = await client.search("sym:USERS")
    files = _all_file_names(result)

    assert any("app.py" in f for f in files), (
        f"sym:USERS should find flask-app/app.py; got: {files}"
    )
    assert any("index.js" in f for f in files), (
        f"sym:USERS should find express-app/index.js; got: {files}"
    )
