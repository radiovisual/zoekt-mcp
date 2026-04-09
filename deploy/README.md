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

## Symbol search & ctags

Zoekt uses [Universal Ctags](https://ctags.io/) at index time to
extract **symbol definitions** — functions, classes, constants,
methods — from every file it ingests. This is what powers the `sym:`
query atom and is also a significant input into Zoekt's result
ranking.

### What ctags actually does

Ctags is a small, language-aware parser that reads source files and
emits a line-per-symbol table of "what is defined where". For
example, given this Python snippet:

```python
USERS = []

def hello():
    return "hi"
```

ctags reports `USERS` as a variable at line 1 and `hello` as a
function at line 3. Zoekt stores those offsets in the shard alongside
the full-text index, so a later query for `sym:hello` can return
*only* the definition sites — no docstring hits, no comment matches,
no string literals.

### Why Zoekt benefits from it

Two concrete wins:

1. **`sym:` queries work at all.** Without ctags, Zoekt has no idea
   what's a symbol and what's prose. `sym:hello` on a ctags-less
   index returns zero matches even when the file literally contains
   `def hello():`.
2. **Better ranking on content queries.** Even for normal keyword
   searches, Zoekt boosts files where the query word is a defined
   symbol. So searching `httpClient` surfaces the file that
   *declares* `httpClient` above the hundred files that *reference*
   it. Without ctags, that boost is gone and ranking falls back to
   pure ngram frequency.

### Where our workflow gets ctags

The `sourcegraph/zoekt-indexserver:latest` image used by
`deploy/docker-compose.yml` already ships Universal Ctags 6.1.0 at
`/usr/local/bin/universal-ctags`. `zoekt-git-index` picks it up
automatically — there is no flag to set and no config to write.

You can verify the binary is present inside the image:

```bash
docker run --rm --entrypoint sh sourcegraph/zoekt-indexserver:latest \
  -c 'universal-ctags --version | head -1'
# Universal Ctags 6.1.0, Copyright (C) 2015-2023 Universal Ctags Team
```

A comment in `docker-compose.yml` flags this as a load-bearing
assumption so maintainers don't accidentally swap in a slimmer image
that drops ctags.

### Manually verifying ctags ran against your index

Bring the test corpus up so there's something predictable to query:

```bash
./tests/fixtures/up.sh
```

Then run the three checks below.

**Check 1 — the repo metadata advertises symbols.** Every repo in
the `/api/list` response carries a `HasSymbols` flag that Zoekt only
sets to `true` if ctags produced at least one symbol during indexing:

```bash
curl -s -XPOST -d '{"Q":"repo:."}' http://localhost:6070/api/list \
  | python3 -c 'import json,sys; \
      [print(r["Repository"]["Name"], r["Repository"]["HasSymbols"]) \
       for r in json.load(sys.stdin)["List"]["Repos"]]'
# flask-app   True
# express-app True
```

If you see `False`, ctags either wasn't on `$PATH` or crashed —
check `docker logs zoekt-mcp-indexer`.

**Check 2 — a `sym:` query resolves to a definition site.** The
examples corpus is deliberately shaped so that `def hello()` exists
in `flask-app/app.py`. A `sym:` query should narrow directly to it:

```bash
curl -s -XPOST -d '{"Q":"sym:hello lang:python"}' \
  http://localhost:6070/api/search \
  | python3 -c 'import json,sys; \
      r=json.load(sys.stdin)["Result"]; \
      print("matches:", r["MatchCount"]); \
      [print(" ", f["FileName"]) for f in (r.get("Files") or [])]'
# matches: 1
#   app.py
```

Compare that with a plain content search for `hello` — you'll see
extra hits in docstrings, comments, and string literals. That's the
ranking/precision win ctags gives you.

**Check 3 — cross-language symbol search.** Both `flask-app/app.py`
and `express-app/index.js` declare a top-level `USERS` constant.
ctags understands both, so a single `sym:USERS` query should span
languages:

```bash
curl -s -XPOST -d '{"Q":"sym:USERS"}' http://localhost:6070/api/search \
  | python3 -c 'import json,sys; \
      r=json.load(sys.stdin)["Result"]; \
      [print(f["FileName"], f["Language"]) for f in (r.get("Files") or [])]'
# app.py    Python
# index.js  JavaScript
```

All three of these are encoded as assertions in
`tests/test_integration.py` (`test_index_has_symbols_flag`,
`test_sym_search_finds_python_function`,
`test_sym_search_cross_language_constant`), so `pytest
tests/test_integration.py -v` will fail loudly if ctags ever stops
working.

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
- **`sym:` queries return nothing / `HasSymbols` is `false`**: ctags
  either wasn't on `$PATH` in the indexer container or crashed at
  runtime. See the [Symbol search & ctags](#symbol-search--ctags)
  section above for the three-step verification recipe.
