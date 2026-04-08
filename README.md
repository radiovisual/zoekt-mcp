# zoekt-mcp

An [MCP](https://modelcontextprotocol.io) server that exposes
[Sourcegraph Zoekt](https://github.com/sourcegraph/zoekt) code search to any
MCP-capable AI agent — Claude Code, Claude Desktop, Cursor, MCP Inspector,
etc. — so the agent can run fast, indexed, regex/symbol-aware code search
over your repositories regardless of the language you're working in.

- **MCP server:** Python, built on
  [FastMCP](https://github.com/modelcontextprotocol/python-sdk), runs over
  stdio so clients can spawn it as a subprocess.
- **Backend:** a `zoekt-webserver` you bring up via the bundled Docker
  Compose stack (or point the server at any existing zoekt-webserver).
- **Tools exposed:** `search_code`, `list_repos`, `get_file`.

## Architecture

```
Claude Code / Desktop / Cursor  ──stdio──▶  zoekt-mcp (Python)  ──HTTP──▶  zoekt-webserver (Docker)
                                                                                  ▲
                                                                                  │ indexes
                                                                            examples/*
```

## Quickstart

### 1. Bring up the zoekt backend

```bash
docker compose -f deploy/docker-compose.yml up -d
```

The `zoekt-indexer` service indexes everything under `examples/` into a
named volume, then `zoekt-webserver` serves the HTTP JSON API on port
`6070`. See [`deploy/README.md`](deploy/README.md) for details, including
how to re-index after editing `examples/`.

Sanity check:

```bash
curl -s http://localhost:6070/healthz                                        # -> "OK"
curl -s -XPOST -d '{"Q":"def hello"}' http://localhost:6070/api/search | head -c 400
```

### 2. Install the MCP server

Using [uv](https://docs.astral.sh/uv/) (recommended):

```bash
# Run it without installing (works from a checkout of this repo):
uvx --from . zoekt-mcp --backend http://localhost:6070

# Or install it so `zoekt-mcp` is on $PATH:
uv tool install .
```

If you prefer pip/pipx:

```bash
pipx install .
zoekt-mcp --backend http://localhost:6070
```

### 3. Wire it into your MCP client

#### Claude Code (`~/.claude.json`)

```json
{
  "mcpServers": {
    "zoekt": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "/absolute/path/to/zoekt-mcp", "zoekt-mcp"],
      "env": { "ZOEKT_URL": "http://localhost:6070" }
    }
  }
}
```

Or with the CLI:

```bash
claude mcp add zoekt uvx --from /absolute/path/to/zoekt-mcp zoekt-mcp
```

#### Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS)

```json
{
  "mcpServers": {
    "zoekt": {
      "command": "uvx",
      "args": ["--from", "/absolute/path/to/zoekt-mcp", "zoekt-mcp"],
      "env": { "ZOEKT_URL": "http://localhost:6070" }
    }
  }
}
```

Restart the client and the three tools (`search_code`, `list_repos`,
`get_file`) should appear.

## Tool surface

| Tool | Parameters | Returns |
|------|------------|---------|
| `search_code` | `query: str`, `max_results: int = 50`, `context_lines: int = 3` | `{query, file_count, match_count, duration_ms, files: [{repo, file, language, branches, matches: [{line, text, snippet, before, after}]}]}` |
| `list_repos` | `filter: str = ""` (optional `repo:` atom) | `{count, repos: [{name, url, branches, index_time}]}` |
| `get_file` | `repo: str`, `path: str`, `branch: str = "HEAD"` | `{repo, path, branch, content}` |

### Query language

Zoekt's query DSL ([full reference](https://github.com/sourcegraph/zoekt/blob/main/doc/query_syntax.md)):

| Atom | Example | Meaning |
|------|---------|---------|
| `repo:` | `repo:flask-app` | Restrict to repos whose name matches (regex) |
| `file:` | `file:app.py` | Restrict to file paths matching |
| `lang:` | `lang:python` | Restrict to a language |
| `sym:` | `sym:list_users` | Match symbol definitions |
| `case:yes` | `case:yes Foo` | Case-sensitive content match |
| `/regex/` | `/users?/` | Regex content match |
| (whitespace) | `lang:go func main` | Boolean AND |
| `or` | `def hello or function hello` | Boolean OR |

## Manual testing with MCP Inspector

```bash
npx @modelcontextprotocol/inspector uvx --from . zoekt-mcp
```

The Inspector opens a browser UI on `http://localhost:6274`. Under **Tools**
→ **search_code**, try:

- `lang:python def hello` — expect a match in `flask-app/app.py`
- `lang:javascript USERS` — expect a match in `express-app/index.js`
- `sym:users` — expect matches in **both** examples

Under **Tools → list_repos**, an empty filter should return both
`flask-app` and `express-app`.

## Automated tests

```bash
# Unit tests (no Docker required)
uv run pytest tests/test_client_unit.py -v

# Integration tests (require the docker-compose stack to be up)
docker compose -f deploy/docker-compose.yml up -d
uv run pytest tests/test_integration.py -v
```

The integration tests skip automatically when `ZOEKT_URL` is unreachable,
so `uv run pytest` in a fresh checkout without Docker still passes.

## Configuration

| Setting | Env var | Flag | Default |
|---------|---------|------|---------|
| Zoekt backend URL | `ZOEKT_URL` | `--backend` | `http://localhost:6070` |
| HTTP timeout (s) | `ZOEKT_TIMEOUT` | `--timeout` | `30` |

## Repo layout

```
zoekt-mcp/
├── src/zoekt_mcp/         # the Python MCP server
├── tests/                 # unit + integration tests
├── deploy/                # docker-compose for zoekt-webserver
└── examples/
    ├── flask-app/         # tiny Flask verification corpus
    └── express-app/       # tiny Express verification corpus
```

## License

MIT — see [`LICENSE`](LICENSE).
