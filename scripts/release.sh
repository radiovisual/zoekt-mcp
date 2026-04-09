#!/usr/bin/env bash
#
# scripts/release.sh — cut a zoekt-mcp release in one command.
#
# Usage:
#     ./scripts/release.sh 0.2.0          # real release
#     ./scripts/release.sh 0.2.0 --dry-run # preview every step, change nothing
#
# What it does, in order:
#   1. Sanity-checks the environment: clean working tree, on `main`,
#      up to date with origin, version looks like PEP 440, no
#      pre-existing `vX.Y.Z` tag.
#   2. Bumps the `version` field in pyproject.toml to the argument.
#   3. Commits the bump as `chore(release): vX.Y.Z`.
#   4. Creates an annotated tag `vX.Y.Z`.
#   5. Pushes main and the tag to origin in one step.
#
# On push, .github/workflows/release.yml takes over: verify-version,
# build wheel, publish to PyPI (Trusted Publishing) and ghcr.io
# (multi-arch), then cut the GitHub release with compose assets.
#
# If you prefer not to use this script, RELEASING.md documents the
# exact manual flow. The two paths produce byte-identical results.

set -euo pipefail

# ---------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------

DRY_RUN=false
VERSION=""

usage() {
  cat <<'EOF'
Usage: scripts/release.sh <version> [--dry-run]

Arguments:
  <version>   New PEP 440 version, e.g. 0.2.0 or 1.0.0rc1. Without leading "v".
  --dry-run   Print every step but don't modify files, commit, tag, or push.

Examples:
  scripts/release.sh 0.2.0
  scripts/release.sh 1.0.0rc1
  scripts/release.sh 0.3.0 --dry-run
EOF
}

for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=true ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "error: unknown flag: ${arg}" >&2; usage >&2; exit 2 ;;
    *)
      if [ -n "${VERSION}" ]; then
        echo "error: more than one version argument: '${VERSION}' and '${arg}'" >&2
        usage >&2
        exit 2
      fi
      VERSION="${arg}"
      ;;
  esac
done

if [ -z "${VERSION}" ]; then
  echo "error: version argument is required" >&2
  usage >&2
  exit 2
fi

TAG="v${VERSION}"

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m==>\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

run() {
  if ${DRY_RUN}; then
    printf '\033[1;36m[dry-run]\033[0m %s\n' "$*"
  else
    eval "$@"
  fi
}

# ---------------------------------------------------------------------
# 1. Sanity checks
# ---------------------------------------------------------------------

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" \
  || die "not inside a git repository"
cd "${REPO_ROOT}"

say "Release target: ${TAG}  (dry-run=${DRY_RUN})"

# PEP 440-ish version check. Deliberately permissive — we don't try to
# replicate the full spec, just catch obvious typos like `v0.2.0` or
# `0.2` or `0.2.0.dev` (trailing dot).
if ! printf '%s' "${VERSION}" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+([abc]|rc|\.post|\.dev)?[0-9]*$'; then
  die "version '${VERSION}' does not look like a PEP 440 release version (e.g. 0.2.0, 1.0.0rc1, 0.2.0.post1)"
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "${CURRENT_BRANCH}" != "main" ]; then
  die "releases must be cut from main (currently on '${CURRENT_BRANCH}')"
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  die "working tree has uncommitted changes. Stash or commit before releasing."
fi

say "Fetching origin/main to check we are up to date..."
git fetch --quiet origin main

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse origin/main)"
if [ "${LOCAL}" != "${REMOTE}" ]; then
  die "local main (${LOCAL:0:8}) differs from origin/main (${REMOTE:0:8}). Pull or push before releasing."
fi

if git rev-parse --verify --quiet "refs/tags/${TAG}" >/dev/null; then
  die "tag ${TAG} already exists locally"
fi
if git ls-remote --exit-code --tags origin "refs/tags/${TAG}" >/dev/null 2>&1; then
  die "tag ${TAG} already exists on origin"
fi

# Read the current version via tomllib so we get the same answer the
# release workflow's verify-version step will read.
CURRENT_VERSION="$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"

# Decide whether we need to bump. The tag-already-exists check above
# has already fired, so if CURRENT_VERSION matches VERSION we are in
# the "tag the current pyproject version as-is" path — which is
# exactly what the very first release (or any release from a commit
# that already bumped pyproject.toml in an earlier PR) looks like.
# Skip the bump + commit in that case and go straight to tag + push.
if [ "${CURRENT_VERSION}" = "${VERSION}" ]; then
  SKIP_BUMP=true
  say "pyproject.toml is already at ${VERSION}; skipping bump + commit, tagging HEAD as-is"
else
  SKIP_BUMP=false
  say "pyproject.toml is at ${CURRENT_VERSION}, bumping to ${VERSION}"
fi

# ---------------------------------------------------------------------
# 2–5. Bump, commit, tag, push
# ---------------------------------------------------------------------

if ! ${SKIP_BUMP}; then
  command -v uv >/dev/null 2>&1 \
    || die "uv is required to bump pyproject.toml (install from https://docs.astral.sh/uv/)"

  say "Bumping pyproject.toml version"
  run "uv version '${VERSION}'"

  say "Committing the bump"
  run "git add pyproject.toml uv.lock 2>/dev/null || git add pyproject.toml"
  run "git commit -m 'chore(release): ${TAG}'"
fi

say "Creating annotated tag ${TAG}"
run "git tag -a '${TAG}' -m 'Release ${TAG}'"

say "Pushing main and tag to origin"
if ${SKIP_BUMP}; then
  say "(main is already up to date on origin — pushing tag only)"
else
  run "git push origin main"
fi
run "git push origin '${TAG}'"

if ${DRY_RUN}; then
  warn "dry-run complete — nothing was actually modified, committed, tagged, or pushed."
  exit 0
fi

say "Done. Release workflow is now running:"
say "  https://github.com/radiovisual/zoekt-mcp/actions/workflows/release.yml"
