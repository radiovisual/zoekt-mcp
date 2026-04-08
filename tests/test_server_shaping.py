"""Unit tests for the response shaping helpers in :mod:`zoekt_mcp.server`.

These exercise the pure functions that turn raw zoekt JSON into the
trimmed shapes the MCP tools return. The fixtures are taken directly
from a live ``zoekt-webserver -rpc`` response against the examples/
corpus, so they document the real API contract.
"""

from __future__ import annotations

import base64

from zoekt_mcp.server import (
    _decode_line,
    _shape_chunk_match,
    _shape_list_result,
    _shape_search_result,
)


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def test_decode_line_handles_base64() -> None:
    assert _decode_line(_b64("def hello():")) == "def hello():"


def test_decode_line_falls_back_on_non_base64() -> None:
    # If the value is already plain text (older zoekt, future API change),
    # we should return it unchanged rather than crash.
    assert _decode_line("plain text") == "plain text"


def test_decode_line_handles_none_and_empty() -> None:
    assert _decode_line(None) == ""
    assert _decode_line("") == ""


def test_shape_search_result_matches_live_shape() -> None:
    raw = {
        "FileCount": 1,
        "MatchCount": 2,
        "Duration": 715529,
        "Files": [
            {
                "FileName": "app.py",
                "Repository": "flask-app",
                "Language": "Python",
                "Branches": ["main"],
                "Score": 85000000010,
                "LineMatches": [
                    {
                        "LineNumber": 20,
                        "Line": _b64("def hello():"),
                        "LineStart": 459,
                        "LineEnd": 472,
                        "LineFragments": [
                            {"LineOffset": 0, "MatchLength": 3},
                            {"LineOffset": 4, "MatchLength": 5},
                        ],
                        "Before": None,
                        "After": None,
                    }
                ],
            }
        ],
    }

    shaped = _shape_search_result("def hello", raw)

    assert shaped["query"] == "def hello"
    assert shaped["file_count"] == 1
    assert shaped["match_count"] == 2
    assert shaped["duration_ns"] == 715529
    assert len(shaped["files"]) == 1

    f = shaped["files"][0]
    assert f["repo"] == "flask-app"
    assert f["file"] == "app.py"
    assert f["language"] == "Python"
    assert f["branches"] == ["main"]

    m = f["matches"][0]
    assert m["line"] == 20
    assert m["text"] == "def hello():"
    assert m["highlights"] == [
        {"line_offset": 0, "length": 3},
        {"line_offset": 4, "length": 5},
    ]


def test_shape_search_result_prefers_chunk_matches_with_symbols() -> None:
    # Shape of a sym:users hit taken from a live sourcegraph/zoekt-webserver
    # response. The client sends Opts.ChunkMatches=true by default, which
    # causes zoekt to return ChunkMatches (multi-line context blocks with
    # per-range byte offsets + symbol info) instead of LineMatches.
    raw = {
        "FileCount": 1,
        "MatchCount": 2,
        "Duration": 110200,
        "Files": [
            {
                "FileName": "index.js",
                "Repository": "express-app",
                "Language": "JavaScript",
                "Branches": ["main"],
                "Score": 7901,
                "ChunkMatches": [
                    {
                        "Content": _b64("const USERS = [\n  {id: 1},\n"),
                        "ContentStart": {"ByteOffset": 264, "LineNumber": 11, "Column": 1},
                        "Ranges": [
                            {
                                "Start": {"ByteOffset": 295, "LineNumber": 11, "Column": 7},
                                "End": {"ByteOffset": 300, "LineNumber": 11, "Column": 12},
                            }
                        ],
                        "SymbolInfo": [
                            {"Sym": "USERS", "Kind": "variable", "Parent": "", "ParentKind": ""}
                        ],
                        "BestLineMatch": 11,
                        "Score": 7901,
                    }
                ],
            }
        ],
    }

    shaped = _shape_search_result("sym:users", raw)
    file = shaped["files"][0]
    assert len(file["matches"]) == 1

    match = file["matches"][0]
    assert match["line"] == 11
    assert match["start_line"] == 11
    assert "const USERS" in match["text"]
    assert match["ranges"] == [
        {"start_line": 11, "start_col": 7, "end_line": 11, "end_col": 12}
    ]
    assert match["symbols"] == [{"name": "USERS", "kind": "variable", "parent": None}]


def test_shape_chunk_match_survives_missing_subfields() -> None:
    shaped = _shape_chunk_match({})
    assert shaped["line"] is None
    assert shaped["text"] == ""
    assert shaped["ranges"] == []
    assert shaped["symbols"] is None


def test_shape_search_result_tolerates_missing_fields() -> None:
    shaped = _shape_search_result("q", {})
    assert shaped == {
        "query": "q",
        "file_count": None,
        "match_count": None,
        "duration_ns": None,
        "files": [],
    }


def test_shape_list_result_matches_live_shape() -> None:
    raw = {
        "Repos": [
            {
                "Repository": {
                    "Name": "flask-app",
                    "URL": "",
                    "Source": "/tmp/flask-app",
                    "Branches": [{"Name": "main", "Version": "abc123"}],
                    "HasSymbols": True,
                },
                "IndexMetadata": {"IndexTime": "2026-04-08T15:47:31Z"},
                "Stats": {"Documents": 3},
            },
            {
                "Repository": {
                    "Name": "express-app",
                    "URL": "",
                    "Source": "/tmp/express-app",
                    "Branches": [{"Name": "main", "Version": "def456"}],
                    "HasSymbols": True,
                },
                "IndexMetadata": {"IndexTime": "2026-04-08T15:47:31Z"},
                "Stats": {"Documents": 3},
            },
        ]
    }

    shaped = _shape_list_result(raw)

    assert shaped["count"] == 2
    names = [r["name"] for r in shaped["repos"]]
    assert names == ["flask-app", "express-app"]
    assert shaped["repos"][0]["branches"] == ["main"]
    assert shaped["repos"][0]["source"] == "/tmp/flask-app"
    assert shaped["repos"][0]["has_symbols"] is True
    assert shaped["repos"][0]["index_time"] == "2026-04-08T15:47:31Z"


def test_shape_list_result_empty() -> None:
    assert _shape_list_result({}) == {"count": 0, "repos": []}
