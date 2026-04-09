"""Unit tests for :mod:`zoekt_mcp.client`.

All HTTP traffic is mocked with respx so these tests run offline. They
verify that the client posts the expected JSON to the expected URLs and
unwraps responses the way callers expect.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from zoekt_mcp.client import (
    DEFAULT_BACKEND_URL,
    ZoektBackendError,
    ZoektClient,
)

SEARCH_URL = f"{DEFAULT_BACKEND_URL}/api/search"
LIST_URL = f"{DEFAULT_BACKEND_URL}/api/list"
PRINT_URL = f"{DEFAULT_BACKEND_URL}/print"


@pytest.fixture
async def client() -> ZoektClient:
    async with ZoektClient() as c:
        yield c


@respx.mock
async def test_search_posts_expected_payload_and_unwraps_result(client: ZoektClient) -> None:
    route = respx.post(SEARCH_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "Result": {
                    "Files": [{"fileName": "app.py", "matches": []}],
                    "Stats": {"FileCount": 1},
                }
            },
        )
    )

    result = await client.search("lang:python def hello", num_context_lines=5)

    assert route.called
    sent = route.calls.last.request
    assert sent.url == SEARCH_URL
    body = sent.content.decode()
    assert '"Q":"lang:python def hello"' in body
    assert '"NumContextLines":5' in body
    assert '"ChunkMatches":true' in body
    assert result == {
        "Files": [{"fileName": "app.py", "matches": []}],
        "Stats": {"FileCount": 1},
    }


@respx.mock
async def test_list_repos_unwraps_list_key(client: ZoektClient) -> None:
    respx.post(LIST_URL).mock(
        return_value=httpx.Response(
            200,
            json={"List": {"Repos": [{"Repository": {"Name": "flask-app"}}]}},
        )
    )

    result = await client.list_repos()

    assert result == {"Repos": [{"Repository": {"Name": "flask-app"}}]}


@respx.mock
async def test_search_raises_on_5xx(client: ZoektClient) -> None:
    respx.post(SEARCH_URL).mock(return_value=httpx.Response(500, text="boom"))

    with pytest.raises(ZoektBackendError) as exc_info:
        await client.search("foo")

    assert exc_info.value.status_code == 500
    assert exc_info.value.body == "boom"


@respx.mock
async def test_search_raises_on_invalid_json(client: ZoektClient) -> None:
    respx.post(SEARCH_URL).mock(return_value=httpx.Response(200, text="not json at all"))

    with pytest.raises(ZoektBackendError) as exc_info:
        await client.search("foo")

    assert "invalid JSON" in str(exc_info.value)
    assert exc_info.value.body == "not json at all"


@respx.mock
async def test_get_file_returns_raw_text(client: ZoektClient) -> None:
    raw_source = 'def hello():\n    return "world"\n'
    route = respx.get(PRINT_URL).mock(
        return_value=httpx.Response(
            200,
            text=raw_source,
            headers={"content-type": "text/plain; charset=utf-8"},
        )
    )

    content = await client.get_file("flask-app", "app.py", branch="main")

    assert content == raw_source
    assert route.called
    sent = route.calls.last.request
    # The client must request ?format=raw, otherwise zoekt returns HTML.
    assert "format=raw" in str(sent.url)
    assert "r=flask-app" in str(sent.url)
    assert "f=app.py" in str(sent.url)
    assert "b=main" in str(sent.url)


@respx.mock
async def test_get_file_raises_on_404(client: ZoektClient) -> None:
    respx.get(PRINT_URL).mock(return_value=httpx.Response(404, text="not found"))

    with pytest.raises(ZoektBackendError) as exc_info:
        await client.get_file("flask-app", "missing.py")

    assert exc_info.value.status_code == 404
