#!/usr/bin/env bash
#
# Rebuild the zoekt index without bouncing the webserver.
#
# Runs just the `zoekt-indexer` one-shot service from docker-compose.yml,
# which re-indexes everything under ../examples into the shared volume.
# The webserver picks up new shards on its next query.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

docker compose run --rm zoekt-indexer
