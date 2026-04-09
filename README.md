# zoekt-mcp

[![CI](https://github.com/radiovisual/zoekt-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/radiovisual/zoekt-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/zoekt-mcp.svg)](https://pypi.org/project/zoekt-mcp/)
[![ghcr.io](https://img.shields.io/badge/ghcr.io-zoekt--mcp-blue)](https://github.com/radiovisual/zoekt-mcp/pkgs/container/zoekt-mcp)
[![License](https://img.shields.io/github/license/radiovisual/zoekt-mcp.svg)](LICENSE)

An [MCP](https://modelcontextprotocol.io) server that exposes
[Sourcegraph Zoekt](https://github.com/sourcegraph/zoekt) code search to any
MCP-capable AI agent — Claude Code, Claude Desktop, Cursor, MCP Inspector,
etc. — so the agent can run fast, indexed, regex/symbol-aware code search
over your repositories regardless of the language you're working in.

- **MCP server:** Python, built on
  [FastMCP](https://github.com/modelcontextprotocol/python-sdk), runs over
  stdio so clients can spawn it as a subprocess. Published to
  [PyPI](https://pypi.org/project/zoekt-mcp/) and
  [ghcr.io](https://github.com/radiovisual/zoekt-mcp/pkgs/container/zoekt-mcp)
  so **no clone is required to use it**.
- **Backend:** a `zoekt-webserver` you run yourself via the Docker
  Compose file attached to every
  [GitHub release](https://github.com/radiovisual/zoekt-mcp/releases/latest) —
  or point the MCP server at any existing zoekt-webserver you have
  lying around.
- **Tools exposed:** `search_code`, `list_repos`, `get_file`.

## Architecture

```mermaid
flowchart LR
    subgraph Client["MCP client"]
        CC["Claude Code<br/>Claude Desktop<br/>Cursor, etc."]
    end

    subgraph Server["zoekt-mcp (Python)"]
        Tools["search_code<br/>list_repos<br/>get_file"]
    end

    subgraph Backend["Docker: zoekt backend"]
        Web["zoekt-webserver"]
        Idx[("zoekt index<br/>named volume")]
        Indexer["zoekt-indexer<br/>(one-shot)"]
    end

    Code[("Your code<br/>bind mount")]

    CC <-->|"stdio<br/>MCP protocol"| Tools
    Tools <-->|"HTTP JSON<br/>/api/search<br/>/api/list<br/>/print"| Web
    Web --> Idx
    Code --> Indexer
    Indexer --> Idx
```

### How a single search flows through the system

```mermaid
sequenceDiagram
    actor You
    participant Claude as Claude Code
    participant MCP as zoekt-mcp
    participant Web as zoekt-webserver
    participant Idx as zoekt index

    You->>Claude: "where is getVideoId defined?"
    Claude->>MCP: search_code("sym:getVideoId")
    MCP->>Web: POST /api/search
    Web->>Idx: scan shards
    Idx-->>Web: matches + ctags symbols
    Web-->>MCP: raw JSON result
    Note over MCP: trim to {repo, file,<br/>line, text, symbols}
    MCP-->>Claude: shaped result
    Claude-->>You: "src/index.js:17 (function)"
```

## Quickstart

Getting from "nothing installed" to "Claude can search my code" is
three steps: install the MCP server, run the backend, wire it into
your client. No git clone required in any of them.

### Prerequisites

You need exactly one of these to run the MCP server, plus Docker for
the backend:

- **[uv](https://docs.astral.sh/uv/) on your `PATH`** — for the
  `uvx zoekt-mcp` install path. MCP clients spawn the server via
  `uvx`, so `which uv` must resolve in whatever shell your client
  launches processes in. Install once per machine:

  ```bash
  # Official installer (macOS / Linux)
  curl -LsSf https://astral.sh/uv/install.sh | sh

  # Homebrew
  brew install uv

  # pipx
  pipx install uv
  ```

  The installer drops `uv` and `uvx` into `~/.local/bin/` (Linux/macOS)
  or `%USERPROFILE%\.local\bin\` (Windows). Verify with `uv --version`.

- **…or Docker** — for the `docker run ghcr.io/radiovisual/zoekt-mcp`
  install path. Any recent Docker Desktop or engine works. You need
  Docker anyway for the backend, so this path saves you from
  installing `uv` if you don't already have it.

And for the backend:

- **Docker with Compose v2** — runs `zoekt-webserver` and the
  one-shot indexer via the compose file attached to every
  [release](https://github.com/radiovisual/zoekt-mcp/releases/latest).

### 1. Start the backend (once per machine)

The zoekt backend is a regular Docker Compose stack you run
yourself — zoekt-mcp does **not** lifecycle-manage it. Grab the
compose file and helper script from the latest GitHub release and
bring them up against whatever directory holds your code:

```bash
# Fetch the two files you need from the latest release.
mkdir -p ~/.zoekt-mcp && cd ~/.zoekt-mcp
curl -LO https://github.com/radiovisual/zoekt-mcp/releases/latest/download/docker-compose.yml
curl -LO https://github.com/radiovisual/zoekt-mcp/releases/latest/download/index.sh
chmod +x index.sh

# Point the indexer at any parent directory on your machine.
# Every top-level subdirectory becomes one searchable repo.
echo "ZOEKT_REPOS_DIR=/home/you/code" > .env

# Bring up zoekt-webserver + the one-shot indexer.
docker compose up -d
```

So if `/home/you/code` looks like this:

```text
~/code/
├── project-a/       → indexed as zoekt repo "project-a"
├── project-b/       → indexed as zoekt repo "project-b"
└── scratch-notes/   → indexed as zoekt repo "scratch-notes"
```

…zoekt indexes **all three repos in one pass** and you can scope any
query with `repo:project-a` — or leave `repo:` off to search across
everything at once. See
[Indexing multiple codebases](#indexing-multiple-codebases) below for
more on the one-server-many-repos model.

Sanity check:

```bash
curl -s -XPOST -d '{"Q":"repo:."}' http://localhost:6070/api/list \
  | python3 -m json.tool | head -20
```

You should see each subdirectory of `ZOEKT_REPOS_DIR` listed as a
zoekt repo.

> On macOS / Windows Docker Desktop, the path you pick must be under
> an allowed file-sharing root (check Docker Desktop → Settings →
> Resources → File Sharing). On Linux there's no such restriction.
>
> **Just want to try it without touching your real code directory?**
> Clone the repo and use the in-tree test fixture:
> `./tests/fixtures/up.sh` — see [Development](#development) at the
> bottom of this file.

### 2. Wire the MCP server into your client

Two install paths — pick whichever matches your existing tooling.
Both end up running the same versioned server binary; the only
difference is how it's launched.

#### Path A — `uvx` (recommended if you already have uv)

`uvx` downloads the latest `zoekt-mcp` from PyPI on first
invocation, caches it, and spawns it. No permanent install, no venv
to manage.

**Claude Code (`~/.claude.json`):**

```json
{
  "mcpServers": {
    "zoekt": {
      "type": "stdio",
      "command": "uvx",
      "args": ["zoekt-mcp"],
      "env": { "ZOEKT_URL": "http://localhost:6070" }
    }
  }
}
```

Or via the `claude` CLI:

```bash
claude mcp add zoekt \
    --env ZOEKT_URL=http://localhost:6070 \
    -- uvx zoekt-mcp
```

**Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):**

```json
{
  "mcpServers": {
    "zoekt": {
      "command": "uvx",
      "args": ["zoekt-mcp"],
      "env": { "ZOEKT_URL": "http://localhost:6070" }
    }
  }
}
```

**Cursor (`~/.cursor/mcp.json` or `.cursor/mcp.json` in a project):**

```json
{
  "mcpServers": {
    "zoekt": {
      "command": "uvx",
      "args": ["zoekt-mcp"],
      "env": { "ZOEKT_URL": "http://localhost:6070" }
    }
  }
}
```

To pin a specific version instead of always using the latest:

```json
"args": ["zoekt-mcp==0.1.0"]
```

#### Path B — Docker image (no Python tooling required)

If you already have Docker running for the backend and would rather
not install `uv`, use the container image instead. MCP clients
spawn it over stdio exactly like the `uvx` path.

**Claude Code / Claude Desktop / Cursor:**

```json
{
  "mcpServers": {
    "zoekt": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "--network=host",
        "-e", "ZOEKT_URL=http://localhost:6070",
        "ghcr.io/radiovisual/zoekt-mcp:latest"
      ]
    }
  }
}
```

On Docker Desktop (macOS/Windows) the host isn't reachable via
`localhost` from inside a container. Drop `--network=host` and use
`host.docker.internal` instead:

```json
"args": [
  "run", "-i", "--rm",
  "-e", "ZOEKT_URL=http://host.docker.internal:6070",
  "ghcr.io/radiovisual/zoekt-mcp:latest"
]
```

To pin a specific version, replace `:latest` with the semver tag
(e.g. `:0.1.0`). The image is multi-arch (`linux/amd64` +
`linux/arm64`), so it works on Apple Silicon and ARM Linux hosts
without extra flags.

### 3. Restart the client

Restart Claude Code / Claude Desktop / Cursor and the three tools
(`search_code`, `list_repos`, `get_file`) should appear. Try
something like "where is `getVideoId` defined?" and watch it call
`search_code("sym:getVideoId")`.

## Indexing multiple codebases

**One zoekt-mcp server handles as many repos as you want** — that's
the default. Every top-level subdirectory of `ZOEKT_REPOS_DIR` becomes
a separate searchable repo in one shared index. The `search_code`
tool can scope to a subset with `repo:NAME` (regex matched against
repo names) or leave `repo:` off to search across everything.

If your projects live under different parent directories (e.g.
`~/work/` and `~/personal/`), the simplest fix is to create a single
"index root" directory with symlinks pointing at each project and set
`ZOEKT_REPOS_DIR` to that index root. One server, one config, all
repos searchable.

```bash
mkdir -p ~/.zoekt-root
ln -s ~/work/project-a       ~/.zoekt-root/project-a
ln -s ~/personal/side-thing  ~/.zoekt-root/side-thing

cd ~/.zoekt-mcp
echo "ZOEKT_REPOS_DIR=$HOME/.zoekt-root" > .env
docker compose up -d
```

> Docker has to follow the symlinks when it resolves the bind mount,
> which works on Linux but is hit-or-miss on Docker Desktop. If the
> linked directories don't show up inside the container, fall back
> to putting real directories (or clones) under `~/.zoekt-root`
> instead of symlinks.

### When you actually need two servers

A second zoekt-mcp instance is only worth the setup cost when you
want **fully isolated index pools** — for example, keeping work code
and personal code in completely separate search namespaces, or
running two different backends (e.g. different zoekt versions) side
by side. It is **not** needed just to index more code; one server
with many subdirectories is the right tool for that.

If you genuinely want two instances:

1. Copy `~/.zoekt-mcp/docker-compose.yml` to a second file, e.g.
   `~/.zoekt-mcp/docker-compose.personal.yml`.
2. In the copy, change:
   - the compose project `name:` (e.g. `zoekt-mcp-personal`)
   - the host port mapping (e.g. `6071:6070`)
   - the named volume (e.g. `zoekt-mcp-personal-index`)
   - the container names (e.g. `zoekt-mcp-personal-webserver`)
3. Give the second stack its own env file, e.g.
   `~/.zoekt-mcp/.env.personal`, pointing `ZOEKT_REPOS_DIR` at a
   different directory.
4. Bring each stack up with its own compose file and env file:

   ```bash
   cd ~/.zoekt-mcp
   docker compose up -d
   docker compose -f docker-compose.personal.yml \
     --env-file .env.personal up -d
   ```

5. Wire both into your MCP client as distinct servers — same
   `zoekt-mcp` binary, different `ZOEKT_URL` values:

   ```json
   {
     "mcpServers": {
       "zoekt-work": {
         "command": "uvx",
         "args": ["zoekt-mcp"],
         "env": { "ZOEKT_URL": "http://localhost:6070" }
       },
       "zoekt-personal": {
         "command": "uvx",
         "args": ["zoekt-mcp"],
         "env": { "ZOEKT_URL": "http://localhost:6071" }
       }
     }
   }
   ```

Claude Code sees two independent sets of tools (`search_code` /
`list_repos` / `get_file` from each namespace) and decides which to
call based on the question.

For most users, **one server with a well-populated `ZOEKT_REPOS_DIR`
is all you need.** Don't reach for multi-server unless you have a
concrete reason to isolate.

### Advanced: staging code under a dedicated repos directory

As an alternative to pointing `ZOEKT_REPOS_DIR` at your real code,
you can create a dedicated staging directory and drop clones or
directories into it. Useful when you can't expose your real code
directory to Docker (e.g. corporate file-sharing restrictions on
Docker Desktop), or for one-off experiments with a repo you don't
have locally:

```bash
mkdir -p ~/.zoekt-mcp/repos
git clone https://github.com/myorg/myrepo ~/.zoekt-mcp/repos/myrepo

cd ~/.zoekt-mcp
echo "ZOEKT_REPOS_DIR=$HOME/.zoekt-mcp/repos" > .env
docker compose up -d
```

The trade-off is a **freshness trap**: you now have two copies of
every project — the one you actually edit, and the staged copy.
Re-running the indexer re-reads the staged copy, so you'd need to
`git pull` (or `cp -r` your edits) inside
`~/.zoekt-mcp/repos/myrepo/` before each re-index. Prefer pointing
`ZOEKT_REPOS_DIR` at your live code directory unless you have a
specific reason not to.

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

## Keeping the index fresh

Zoekt searches a **pre-built index**, not your files directly. When
you edit code, the index doesn't auto-update — your next search can
return stale line numbers, miss newly-added symbols, or point Claude
at functions that have moved or been renamed. Stale search is the
main thing that burns tokens, because Claude falls back to reading
whole files with `get_file` when `search_code` returns nothing useful.

Here's what happens every time the indexer runs:

```mermaid
flowchart LR
    Src["Your code<br/>(live files)"]
    Mount["/src<br/>(read-only<br/>bind mount)"]
    Scratch["/tmp/{repo}<br/>(ephemeral<br/>copy)"]
    Git["throwaway<br/>git repo<br/>+ snapshot commit"]
    Shard[("index shard<br/>/data/*.zoekt")]

    Src -->|bind mount| Mount
    Mount -->|cp -r| Scratch
    Scratch -->|"git init; git add -A;<br/>git commit"| Git
    Git -->|zoekt-git-index| Shard
```

The copy to `/tmp/` is ephemeral — it happens fresh on every indexer
run and never touches your real files. Each refresh always reads
whatever is currently in the mounted source directory.

Fortunately, re-indexing is fast (seconds, even for large repos),
runs entirely in Docker, involves no LLM calls, and costs zero
tokens. You just need to decide **how** you want to trigger it.

Because the main quickstart already points `ZOEKT_REPOS_DIR` at your
live code directory, every re-index automatically reflects your
latest edits — no copy step to keep in sync. (If you're on the
[advanced staging workflow](#advanced-staging-code-under-a-dedicated-repos-directory)
instead, update the clones under `~/.zoekt-mcp/repos/` before you
trigger a re-index, otherwise zoekt just re-reads the stale copies.)

### Recipes for triggering the re-index

All four recipes run out-of-band — no Claude, no tokens, no context
window involvement. Pick whichever matches how you work.

#### 1. Manual re-index

Run `~/.zoekt-mcp/index.sh` whenever you know you've made significant
changes. The script runs just the indexer container against the
current `ZOEKT_REPOS_DIR` without bouncing the webserver, so search
stays available throughout.

```bash
~/.zoekt-mcp/index.sh
```

*Good when:* you only use Claude for occasional sessions and don't
mind typing one command before you start. Zero background cost.

#### 2. Cron (scheduled re-index)

Background re-index on a schedule. No manual step, slightly stale
between ticks.

```cron
# Re-index every 15 minutes
*/15 * * * * cd ~/.zoekt-mcp && ./index.sh >/dev/null 2>&1
```

*Good when:* you work on code most days and want fresh-ish search
any time you open Claude. Once an hour is fine for most users.

#### 3. Filesystem watcher

React to file changes in near-real-time via `inotifywait` (Linux)
or `fswatch` (macOS). Catches every edit, idle otherwise.

```bash
# Linux: one-liner, run it in a tmux pane or as a systemd --user service
while inotifywait -r -e modify,create,delete,move \
    --exclude '\.git/|node_modules/|__pycache__/' \
    /path/to/your/code 2>/dev/null; do
  ~/.zoekt-mcp/index.sh
done
```

```bash
# macOS equivalent with fswatch (brew install fswatch)
fswatch -o /Users/you/code | xargs -n1 -I{} ~/.zoekt-mcp/index.sh
```

*Good when:* you want "search is always current, no matter when I
ask." Caveat: on projects with noisy tooling (compilers writing to
build dirs, IDE lockfiles), the excludes list is important — without
them you'll re-index constantly.

#### 4. Claude Code SessionStart hook

Re-index every time you launch a new Claude Code session, so the
first search of every session is guaranteed fresh. This is probably
the best default for most users: no background process, no cron
entry, and freshness is tied exactly to when you'd actually notice
staleness.

```json
// ~/.claude.json
{
  "hooks": {
    "SessionStart": [
      {
        "command": "$HOME/.zoekt-mcp/index.sh"
      }
    ]
  }
}
```

*Good when:* you want zero ongoing processes and guaranteed fresh
search at the moment you actually use Claude. The session start is
blocked on the re-index, but that's a few seconds at most.

### Which one should I pick?

| If you… | Use |
|---------|-----|
| …occasionally fire up Claude and don't mind a manual step | **Recipe 1** (manual) |
| …want "set it and forget it" but tolerate N-minute staleness | **Recipe 2** (cron) |
| …want always-fresh search and can tune the exclude list | **Recipe 3** (watcher) |
| …mostly interact with code via Claude Code sessions | **Recipe 4** (SessionStart hook) |

None of these recipes are exclusive — e.g. running cron *and* the
SessionStart hook is fine if you want both ambient freshness and a
guarantee at session start.

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

## Development

This section is for hacking on zoekt-mcp itself. If you just want to
*use* it, the [Quickstart](#quickstart) above covers everything — no
clone required. Only come here if you want to change the Python
server, run the full test suite, or cut a release.

### Setup

Clone the repo and let `uv` manage the venv for you:

```bash
git clone https://github.com/radiovisual/zoekt-mcp
cd zoekt-mcp
uv sync
```

`uv sync` creates `.venv/`, resolves everything against `uv.lock`, and
installs all runtime + dev dependencies. The dev group (`pytest`,
`pytest-asyncio`, `respx`, `ruff`, `pre-commit`, `pymarkdownlnt`) is
installed by default; pass `uv sync --no-dev` for a runtime-only
install.

Common dev commands:

```bash
uv run pytest                    # run the full test suite
uv run zoekt-mcp --help          # run the CLI from source
uv add <package>                 # add a new runtime dep
uv add --dev <package>           # add a new dev dep
uv lock --upgrade                # refresh uv.lock
```

To run zoekt-mcp from your local clone against a running backend
(e.g. while iterating on the server code):

```bash
uv run zoekt-mcp --zoekt-url http://localhost:6070
```

### Releasing

Releases are fully automated — a tag push triggers the pipeline
that publishes to PyPI and ghcr.io and cuts a GitHub release with
the compose file attached. See [`RELEASING.md`](RELEASING.md) for
the cut-a-release flow (helper script + manual paths) and the
one-time PyPI/GHCR setup required before the first tag.

### Commit routine

Linting and tests are wired into the git flow via a
[pre-commit](https://pre-commit.com) hook so you never have to remember
to run them by hand. After `uv sync`, install both hook types once per
clone:

```bash
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
```

From then on, every `git commit` runs:

- **ruff** (`ruff check` + `ruff format --check`) against staged
  Python files — config lives under `[tool.ruff]` in
  [`pyproject.toml`](pyproject.toml).
- **pymarkdownlnt** (`pymarkdown scan`) against staged Markdown files
  — config lives under `[tool.pymarkdown]` in
  [`pyproject.toml`](pyproject.toml). We disable `MD013` (line length)
  and `MD046` (code block style) because they fight readable prose and
  wide tables, and `MD033` so the troubleshooting `<details>` blocks
  are allowed.

And every `git push` runs the offline pytest suites
(`tests/test_client_unit.py` and `tests/test_server_shaping.py`) before
the push leaves the machine, so a broken test can never hit the remote.
Tests are scoped to `pre-push` rather than `pre-commit` to keep local
commits snappy; the integration suite is excluded because it needs a
running zoekt-webserver.

The hooks shell out to `uv run`, so the tool versions pinned in
`uv.lock` are what runs locally and in CI — no drift between
environments. The same linters **and** the same unit tests run on
every push to `main` and every pull request via
[`.github/workflows/ci.yml`](.github/workflows/ci.yml).

To run everything manually (e.g. before opening a PR):

```bash
uv run pre-commit run --all-files
```

To fix Python formatting in place rather than just checking it:

```bash
uv run ruff format
uv run ruff check --fix
```

## Automated tests

```bash
# Unit tests (no Docker required)
uv run pytest tests/test_client_unit.py tests/test_server_shaping.py -v

# Integration tests: bring the stack up against the examples/ corpus,
# then run the live assertions.
./tests/fixtures/up.sh
uv run pytest tests/test_integration.py -v
./tests/fixtures/down.sh
```

`tests/fixtures/up.sh` sets `ZOEKT_REPOS_DIR=../examples` and invokes
the same `deploy/docker-compose.yml`, so the test fixtures don't leak
into the production deploy path. The integration tests skip
automatically when `ZOEKT_URL` is unreachable, so a plain
`uv run pytest` in a fresh checkout without Docker still passes.

## Configuration

| Setting | Env var | Flag | Default |
|---------|---------|------|---------|
| Zoekt backend URL | `ZOEKT_URL` | `--zoekt-url` | `http://localhost:6070` |
| HTTP timeout (s) | `ZOEKT_TIMEOUT` | `--timeout` | `30` |

The env var and the flag are equivalent — pick whichever fits your
MCP client's config shape better. Most clients set environment
variables via an `"env"` block in their JSON config, which is why
the `uvx` and Docker snippets above use `ZOEKT_URL` rather than
`--zoekt-url`.

## Repo layout

```text
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

## Troubleshooting

Common indexing pitfalls, in Q&A form. Click any question to expand
the answer.

<details>
<summary><b>Q: <code>search_code</code> returns 0 hits for a string I know is in my project. What's wrong?</b></summary>

Nine times out of ten the index doesn't actually contain your code —
zoekt is searching a different (or stale) corpus. The MCP server
itself doesn't filter or rewrite queries; whatever you send goes
straight to `/api/search`, so 0 hits means 0 hits *in the index*.

Diagnose it in three steps:

1. Ask the agent to call `list_repos` (or `curl -s -XPOST -d '{"Q":"repo:."}' http://localhost:6070/api/list`). This is the source of truth for what zoekt can see.
2. If your project isn't in the list, the indexer was pointed somewhere else. Common culprits:
   - `~/.zoekt-mcp/.env` is missing or has the wrong `ZOEKT_REPOS_DIR`, so `docker compose up` indexed an empty or unexpected directory.
   - Someone ran `./tests/fixtures/up.sh` from a dev clone, which sets `ZOEKT_REPOS_DIR=../examples` and indexes only `examples/express-app` and `examples/flask-app`.
   - The indexer wipes `/data/*` on every run, so a previous good run does **not** persist alongside a later one — the most recent indexer invocation is the only thing the webserver can see.
3. Re-run the indexer against the right directory:

    ```bash
    cd ~/.zoekt-mcp
    echo "ZOEKT_REPOS_DIR=/absolute/path/to/parent-of-your-repo" > .env
    docker compose up -d --force-recreate zoekt-indexer
    ```

    `ZOEKT_REPOS_DIR` must be a **parent** directory; every top-level subdirectory under it becomes one repo. Re-run `list_repos` after the indexer exits to confirm.

</details>

<details>
<summary><b>Q: The indexer exits with <code>WARNING: no repositories were indexed</code>. Now what?</b></summary>

The directory pointed at by `ZOEKT_REPOS_DIR` has no top-level
subdirectories the indexer could turn into repos. Set
`ZOEKT_REPOS_DIR` to a parent that already contains your project
subdirectories:

```bash
cd ~/.zoekt-mcp
echo "ZOEKT_REPOS_DIR=$HOME/code" > .env
docker compose up -d
```

Loose files at the top of `ZOEKT_REPOS_DIR` are ignored — the loop
in the compose file only iterates over directories.

</details>

<details>
<summary><b>Q: <code>list_repos</code> shows <code>express-app</code> and <code>flask-app</code> but not my code.</b></summary>

Those are the in-repo verification fixtures under `examples/` in a
dev clone. They end up in your index when something — usually
`tests/fixtures/up.sh` from a local clone — ran the indexer with
`ZOEKT_REPOS_DIR=../examples`. Re-index against your real project
directory (see the first Q&A above) and they'll be replaced; the
indexer wipes `/data/` at the start of every run, so there's no need
to clean up separately.

</details>

<details>
<summary><b>Q: I edited a file but search results still show the old content / line numbers.</b></summary>

The index is a snapshot, not a live view. zoekt only sees what was
in `ZOEKT_REPOS_DIR` the last time the indexer ran. Trigger a refresh
with `~/.zoekt-mcp/index.sh`, or set up one of the four automation
recipes in [Keeping the index fresh](#keeping-the-index-fresh) so it
happens on its own. Re-indexing is fast (seconds, even for large
repos) and runs entirely in Docker — no LLM calls, zero token cost.

</details>

<details>
<summary><b>Q: <code>POST /api/search</code> returns HTML instead of JSON.</b></summary>

The webserver was started without `-rpc`, so `/api/*` falls through
to the HTML search handler. The release-bundled `docker-compose.yml`
already passes `-rpc` (see the `command:` block under
`zoekt-webserver`); if you're running your own zoekt-webserver
elsewhere, add `-rpc` to its argv and restart.

</details>

## License

MIT — see [`LICENSE`](LICENSE).

<!-- mcp-name: io.github.radiovisual/zoekt-mcp -->
