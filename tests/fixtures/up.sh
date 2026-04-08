#!/usr/bin/env bash
#
# Bring up the zoekt backend pointed at the in-repo verification
# corpus (examples/flask-app and examples/express-app) so the
# integration tests have something to search. This is test-only
# wiring — real users of zoekt-mcp should populate deploy/repos/
# with their own code instead.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

# Path is resolved relative to the compose file (deploy/docker-compose.yml),
# so ../examples lands at the repo root's examples/ directory.
export ZOEKT_REPOS_DIR="../examples"

exec docker compose -f deploy/docker-compose.yml up -d "$@"
