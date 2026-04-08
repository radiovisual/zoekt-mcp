# deploy/ — zoekt backend for zoekt-mcp

This directory contains a Docker Compose stack that brings up a local
Sourcegraph Zoekt backend so the Python MCP server has something to
talk to.

## What's here

- **`docker-compose.yml`** — two services:
  - `zoekt-indexer` runs once, indexes every subdirectory of
    `../examples/` into a named volume, then exits.
  - `zoekt-webserver` serves the HTTP JSON API on
    [http://localhost:6070](http://localhost:6070) and reads from the
    same volume.
- **`index.sh`** — helper that reruns just the indexer after you edit
  files under `examples/`.

## Bring it up

From the repo root:

```bash
docker compose -f deploy/docker-compose.yml up -d
```

The indexer runs first; once it exits successfully the webserver
starts. After a few seconds, verify:

```bash
curl -s http://localhost:6070/healthz            # -> "OK"
curl -s -XPOST -d '{"Q":"def hello"}' http://localhost:6070/api/search | head -c 400
```

The search call should return JSON referencing `flask-app/app.py`.

## Re-index after editing examples/

```bash
./deploy/index.sh
```

This re-runs the indexer one-shot and leaves the webserver untouched.

## Tear it down

```bash
docker compose -f deploy/docker-compose.yml down          # stop containers
docker compose -f deploy/docker-compose.yml down -v       # stop + delete index volume
```

## Ports

- **6070** — zoekt-webserver HTTP/JSON API. Override with the
  `ZOEKT_URL` environment variable on the MCP server side if you remap
  the port.

## Troubleshooting

- **Indexer exits immediately with "no such file"**: make sure you ran
  the compose command from the repo root, or pass
  `-f deploy/docker-compose.yml` so the relative `../examples` mount
  resolves correctly.
- **Webserver stays unhealthy**: check `docker logs zoekt-mcp-webserver`.
  If the index directory is empty the server starts but returns empty
  search results — rerun `./deploy/index.sh` to populate it.
