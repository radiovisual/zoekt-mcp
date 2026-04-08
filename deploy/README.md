# deploy/ — zoekt backend for zoekt-mcp

This directory contains a **generic** Docker Compose stack that brings
up a local Sourcegraph Zoekt backend so the Python MCP server has
something to talk to. The compose file is deliberately not tied to any
specific codebase — you point it at whatever directories you want
indexed via the `ZOEKT_REPOS_DIR` environment variable (default:
`./repos`, a gitignored scratch dir alongside this file).

## What's here

- **`docker-compose.yml`** — two services:
  - `zoekt-indexer` is a one-shot. For every top-level subdirectory of
    the source mount it creates a throwaway git repo and runs
    `zoekt-git-index`, writing shards into a named volume.
  - `zoekt-webserver` serves the HTTP JSON API on
    [http://localhost:6070](http://localhost:6070) and reads from the
    same volume.
- **`repos/`** — a local fallback source mount. Empty by default; used
  only if you don't set `ZOEKT_REPOS_DIR` to point at your real code
  directory. Contents are gitignored.
- **`index.sh`** — helper that reruns just the indexer after you edit
  or add sources under the mount.

## Bring it up with your own code (recommended)

Set `ZOEKT_REPOS_DIR` to any parent directory on your machine. Every
top-level subdirectory of that path becomes one searchable repo in
zoekt — one server, many codebases, zero copying.

```bash
# One-line .env file; docker compose picks it up automatically.
echo "ZOEKT_REPOS_DIR=/home/you/code" > deploy/.env

docker compose -f deploy/docker-compose.yml up -d
```

The indexer runs first; once it exits successfully the webserver
starts. Verify:

```bash
curl -s -XPOST -d '{"Q":"repo:."}' http://localhost:6070/api/list \
  | python3 -m json.tool | head -20
```

## Alternative: stage clones under `deploy/repos/`

If you can't expose your real code directory to Docker (e.g. Docker
Desktop file-sharing restrictions) or you just want to stage a one-off
experiment, leave `ZOEKT_REPOS_DIR` unset — it defaults to `./repos`
— and drop clones or plain directories into `deploy/repos/`:

```bash
mkdir -p deploy/repos
git clone https://github.com/myorg/myrepo deploy/repos/myrepo

docker compose -f deploy/docker-compose.yml up -d
```

Caveat: this creates two copies of each project (the one you edit,
and the copy under `deploy/repos/`). Re-running the indexer only sees
the `deploy/repos/` copy, so you have to `git pull` (or `cp -r` your
edits) before re-indexing. Prefer `ZOEKT_REPOS_DIR` for day-to-day
use.

## Bring it up against the in-repo test corpus

The `examples/` directory contains a tiny Flask and Express app used to
smoke-test the MCP server. Don't use it as a production source mount —
use the test fixture helper instead, which sets `ZOEKT_REPOS_DIR`
appropriately:

```bash
./tests/fixtures/up.sh
# ... run integration tests, poke around ...
./tests/fixtures/down.sh
```

## Re-index after editing sources

```bash
./deploy/index.sh
```

This re-runs the indexer one-shot against whatever `ZOEKT_REPOS_DIR`
currently resolves to and leaves the webserver untouched.

## Tear it down

```bash
docker compose -f deploy/docker-compose.yml down          # stop containers
docker compose -f deploy/docker-compose.yml down -v       # stop + delete index volume
```

## Ports

- **6070** — zoekt-webserver HTTP/JSON API. Override with the
  `ZOEKT_URL` environment variable on the MCP server side if you remap
  the host port.

## Environment variables

| Var | Default | Meaning |
|-----|---------|---------|
| `ZOEKT_REPOS_DIR` | `./repos` (relative to `deploy/`) | Directory whose top-level subdirectories get indexed. |

## Troubleshooting

- **"no repositories were indexed"**: `ZOEKT_REPOS_DIR` is empty. Drop
  at least one subdirectory into it (a git clone, a symlink, or a
  plain directory of source files) and rerun.
- **Indexer can't resolve relative paths**: compose volume paths are
  resolved relative to the compose file location (`deploy/`), not your
  current working directory. If you set `ZOEKT_REPOS_DIR` to a relative
  path, make it relative to `deploy/` (e.g. `../examples`).
- **Webserver stays unhealthy**: check `docker logs zoekt-mcp-webserver`.
  If the index directory is empty the server starts but returns empty
  search results — rerun `./deploy/index.sh` to populate it.
