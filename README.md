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

### Prerequisites

- **Docker** — runs the zoekt-webserver backend and the one-shot
  indexer. Any recent Docker Desktop or engine with Compose v2 works.
- **[uv](https://docs.astral.sh/uv/)** — used by your MCP client to
  spawn the Python server on demand. Install it once per machine
  via the [official installer](https://docs.astral.sh/uv/getting-started/installation/),
  Homebrew (`brew install uv`), or `pipx install uv`.

You do **not** need to create a venv or `pip install` anything to
*use* zoekt-mcp. `uv` handles that transparently on first invocation.
A venv is only needed if you want to hack on the server itself — see
[Development setup](#development-setup) below.

### 1. Clone and bring up the backend

You need a clone of this repo for the Docker Compose file and for a
directory to drop indexable code into.

```bash
git clone https://github.com/wuergler/zoekt-mcp
cd zoekt-mcp
```

Drop any git clones or source directories you want searchable into
`deploy/repos/` (gitignored). Each top-level subdirectory becomes one
zoekt repo.

```bash
mkdir -p deploy/repos
git clone https://github.com/myorg/myrepo deploy/repos/myrepo

docker compose -f deploy/docker-compose.yml up -d
```

The `zoekt-indexer` one-shot indexes everything under `deploy/repos/`
into a named volume, then `zoekt-webserver` serves the HTTP JSON API
on port `6070`. See [`deploy/README.md`](deploy/README.md) for details.

Sanity check:

```bash
curl -s http://localhost:6070/healthz                                        # -> "OK"
curl -s -XPOST -d '{"Q":"repo:myrepo func"}' http://localhost:6070/api/search | head -c 400
```

> **Just want to see it work without populating `deploy/repos/`?**
> There's a tiny Flask + Express verification corpus under
> `examples/` plus a fixture helper that points the backend at it:
>
> ```bash
> ./tests/fixtures/up.sh
> ```
>
> See the "Automated tests" section below for details.

### 2. Wire it into your MCP client

`uvx` will build and run the server directly from your clone — no
explicit install step. Point your MCP client at it:

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

> Once zoekt-mcp is published to PyPI, the `--from` argument goes
> away and the config collapses to `"args": ["zoekt-mcp"]` — no
> clone required for the Python side. The backend still needs the
> compose file from this repo.

## Tool surface

| Tool | Parameters | Returns |
|------|------------|---------|
| `search_code` | `query: str`, `max_results: int = 50`, `context_lines: int = 3` | `{query, file_count, match_count, duration_ns, files: [{repo, file, language, branches, matches: [{line, text, ranges, symbols}]}]}` |
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

## Development setup

If you want to hack on the server itself (rather than just use it via
`uvx`), set up a local venv with `uv` bootstrapped inside it. This
keeps `uv` scoped to the project — nothing gets installed globally.

```bash
# 1. Create a venv using the system Python
python3 -m venv .venv

# 2. Bootstrap uv into the venv (one-time, chicken-and-egg step)
.venv/bin/pip install uv

# 3. Let uv take over from here — installs all runtime + dev deps
.venv/bin/uv sync
```

After this, every dev command goes through `.venv/bin/uv`:

```bash
.venv/bin/uv run pytest              # run the full test suite
.venv/bin/uv run zoekt-mcp --help    # run the CLI from source
.venv/bin/uv add <package>           # add a new runtime dep
.venv/bin/uv lock --upgrade          # refresh uv.lock
```

If you activate the venv (`source .venv/bin/activate`), you can drop
the `.venv/bin/` prefix and just call `uv ...` directly.

Dev dependencies (`pytest`, `pytest-asyncio`, `respx`) live in the
`dev` group in [`pyproject.toml`](pyproject.toml) and are installed
by default on `uv sync`. Runtime-only installs can use
`uv sync --no-dev`.

## Automated tests

```bash
# Unit tests (no Docker required)
.venv/bin/uv run pytest tests/test_client_unit.py tests/test_server_shaping.py -v

# Integration tests: bring the stack up against the examples/ corpus,
# then run the live assertions.
./tests/fixtures/up.sh
.venv/bin/uv run pytest tests/test_integration.py -v
./tests/fixtures/down.sh
```

`tests/fixtures/up.sh` sets `ZOEKT_REPOS_DIR=../examples` and invokes
the same `deploy/docker-compose.yml`, so the test fixtures don't leak
into the production deploy path. The integration tests skip
automatically when `ZOEKT_URL` is unreachable, so a plain
`.venv/bin/uv run pytest` in a fresh checkout without Docker still
passes.

## Configuration

| Setting | Env var | Flag | Default |
|---------|---------|------|---------|
| Zoekt backend URL | `ZOEKT_URL` | `--backend` | `http://localhost:6070` |
| HTTP timeout (s) | `ZOEKT_TIMEOUT` | `--timeout` | `30` |

## Repo layout

```
zoekt-mcp/
├── src/zoekt_mcp/         # the Python MCP server
├── tests/
│   ├── test_client_unit.py     # offline unit tests
│   ├── test_integration.py     # live tests (skip when backend down)
│   └── fixtures/               # test-only helpers (up.sh / down.sh)
├── deploy/
│   ├── docker-compose.yml      # generic zoekt backend (env-driven)
│   └── repos/                  # user-populated source mount (gitignored)
└── examples/
    ├── flask-app/              # Flask verification corpus
    └── express-app/            # Express verification corpus
```

## License

MIT — see [`LICENSE`](LICENSE).
