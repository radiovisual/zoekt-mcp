#!/usr/bin/env bash
#
# Rebuild the zoekt index without bouncing the webserver.
#
# Runs just the `zoekt-indexer` one-shot service from docker-compose.yml,
# which re-reads whatever directory is mounted at /src (configured via
# $ZOEKT_REPOS_DIR; defaults to ./repos) and writes fresh shards to the
# shared index volume. The webserver picks up new shards on its next
# query — no restart required.
#
# Safe to run as often as you like: it's a full rebuild, not incremental,
# so each invocation produces a complete, consistent index.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

docker compose run --rm zoekt-indexer
