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
- **`repos/`** — the default source mount. Put real git clones or
  plain source trees under here; each top-level subdirectory becomes
  one searchable repo in zoekt. Contents are gitignored.
- **`index.sh`** — helper that reruns just the indexer after you edit
  or add sources under the mount.

## Bring it up with your own code

```bash
mkdir -p deploy/repos
git clone https://github.com/myorg/myrepo deploy/repos/myrepo
git clone https://github.com/myorg/another deploy/repos/another

docker compose -f deploy/docker-compose.yml up -d
```

The indexer runs first; once it exits successfully the webserver
starts. Verify:

```bash
curl -s http://localhost:6070/healthz            # -> "OK"
curl -s -XPOST -d '{"Q":"repo:myrepo func"}' http://localhost:6070/api/search | head -c 400
```

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
