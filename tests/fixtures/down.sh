#!/usr/bin/env bash
#
# Tear down the test-corpus zoekt backend started by ./up.sh, including
# the shared index volume so the next `./up.sh` re-indexes from
# scratch.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

export ZOEKT_REPOS_DIR="../examples"

exec docker compose -f deploy/docker-compose.yml down -v "$@"
