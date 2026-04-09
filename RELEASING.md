# Releasing zoekt-mcp

This document covers **how** to cut a release. For the design rationale
(why declarative versioning, why multi-arch, why no auto-bump bot),
see the PR that introduced this file.

A release does four things, all wired to a single `v*` tag push:

1. Publishes the wheel + sdist to
   [PyPI](https://pypi.org/project/zoekt-mcp/) via
   [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) —
   no API tokens, no secrets.
2. Builds and pushes a multi-arch (`linux/amd64` + `linux/arm64`)
   container image to
   [`ghcr.io/radiovisual/zoekt-mcp`](https://github.com/radiovisual/zoekt-mcp/pkgs/container/zoekt-mcp).
3. Creates a
   [GitHub release](https://github.com/radiovisual/zoekt-mcp/releases)
   with auto-generated notes from merged PRs, and attaches
   `deploy/docker-compose.yml` + `deploy/index.sh` as downloadable
   assets so users never have to clone the repo to run the backend.
4. Nothing else. The workflow does not bump versions, does not commit
   back to `main`, and does not post to any external system.

## One-time setup (do this before the first release)

These are one-shot manual steps on PyPI and GitHub that the workflow
cannot perform on your behalf. You do them once per project lifetime.

### 1. Register the PyPI Trusted Publisher

On [pypi.org](https://pypi.org):

1. Sign in → **Your account** → **Publishing**.
2. Under **Add a new pending publisher**, fill in:
   - **PyPI project name:** `zoekt-mcp`
   - **Owner:** `radiovisual`
   - **Repository name:** `zoekt-mcp`
   - **Workflow name:** `release.yml`
   - **Environment name:** `pypi`
3. Submit.

"Pending" means the project does not exist on PyPI yet — that is
correct for the first release. The first successful publish converts
the pending publisher into the real one automatically.

### 2. Create the GitHub `pypi` environment

In the repo settings:

1. **Settings → Environments → New environment**.
2. Name it `pypi`. Exactly that string — it's referenced by
   `release.yml`.
3. No secrets, no required reviewers, no rules required. Creating the
   environment is enough. You can add a manual-approval gate later
   without touching the workflow.

### 3. Make the GHCR package public (after the first publish)

The first `publish-ghcr` run creates the package as **private** by
default. After it succeeds once:

1. Open
   [github.com/radiovisual/zoekt-mcp/pkgs/container/zoekt-mcp](https://github.com/radiovisual/zoekt-mcp/pkgs/container/zoekt-mcp).
2. **Package settings → Danger Zone → Change visibility → Public**.

Only needed once. Every subsequent release reuses the same public
package.

## Cutting a release

Two paths, byte-identical results. Pick whichever feels less
error-prone on the day.

### Path A — one-shot helper script (recommended)

```bash
./scripts/release.sh 0.2.0
```

The script:

1. Sanity-checks the environment (clean working tree, on `main`, up
   to date with `origin/main`, tag `v0.2.0` does not already exist,
   version looks like PEP 440).
2. Runs `uv version 0.2.0` to bump `pyproject.toml`.
3. Commits the bump as `chore(release): v0.2.0`.
4. Creates an annotated tag `v0.2.0`.
5. Pushes `main` and the tag to `origin` in one step.

Preview everything without touching the repo:

```bash
./scripts/release.sh 0.2.0 --dry-run
```

Prereleases work the same way with PEP 440 syntax:

```bash
./scripts/release.sh 1.0.0rc1
./scripts/release.sh 0.3.0.post1
```

Note: prerelease tags (containing `-` or PEP 440 pre-release markers
like `rc1`) intentionally do **not** get tagged `:latest` on
`ghcr.io`. Only final releases do.

### Path B — manual (every step by hand)

If the helper script is broken, unavailable, or you want to do
something unusual (e.g. release from a non-`main` branch in an
emergency), run these commands yourself:

```bash
# 1. Bump the version
uv version 0.2.0                                # edits pyproject.toml

# 2. Commit the bump
git commit -am "chore(release): v0.2.0"

# 3. Create an annotated tag at the bump commit
git tag -a v0.2.0 -m "Release v0.2.0"

# 4. Push main and tags together
git push origin main
git push origin v0.2.0
```

That's it. The tag push triggers `.github/workflows/release.yml`,
which handles everything else.

## What happens after the push

Watch the run at
[Actions → Release](https://github.com/radiovisual/zoekt-mcp/actions/workflows/release.yml).
Five jobs run in this order:

```text
verify-version  ─┐
                 ├─▶  publish-pypi  ─┐
build-wheel  ────┤                    ├─▶  create-release
                 └─▶  publish-ghcr ──┘
```

1. **`verify-version`** parses the tag, reads `pyproject.toml` on the
   same commit, and fails if they disagree. Fast and cheap; catches
   the "tagged v0.2.0 but forgot to bump" mistake before anything
   publishes.
2. **`build-wheel`** runs `uv build`, producing `dist/*.whl` and
   `dist/*.tar.gz`. Uploaded as a workflow artifact so `publish-pypi`
   gets the exact same bytes.
3. **`publish-pypi`** downloads the artifact and uses
   [`pypa/gh-action-pypi-publish`](https://github.com/pypa/gh-action-pypi-publish)
   with OIDC. Runs inside the `pypi` environment so deploy-protection
   rules (if you add them) apply here.
4. **`publish-ghcr`** builds a multi-arch image from `Dockerfile` and
   pushes it to
   [`ghcr.io/radiovisual/zoekt-mcp`](https://github.com/radiovisual/zoekt-mcp/pkgs/container/zoekt-mcp)
   with tags derived via
   [`docker/metadata-action`](https://github.com/docker/metadata-action):
   `:0.2.0`, `:0.2`, `:0`, `:latest` for finals; only `:0.2.0-rc1`
   (etc.) for prereleases.
5. **`create-release`** waits for **both** publish jobs to succeed,
   then creates the GitHub release with auto-generated notes
   (categorized by `.github/release.yml`) and attaches
   `deploy/docker-compose.yml` + `deploy/index.sh` as release assets.

If PyPI or GHCR fails, no GitHub release is created. Re-run the
failed job from the Actions UI once the underlying cause is fixed;
the release job runs once both green.

## Verifying the release

After the workflow goes green:

```bash
# PyPI
uvx zoekt-mcp --help
pip index versions zoekt-mcp            # should list the new version

# ghcr.io
docker pull ghcr.io/radiovisual/zoekt-mcp:latest
docker run -i --rm ghcr.io/radiovisual/zoekt-mcp --help

# GitHub release + assets
gh release view v0.2.0
gh release download v0.2.0 -p docker-compose.yml -p index.sh
```

## What the workflow does NOT do

Called out explicitly so nobody spends time looking for it:

- **Does not bump `pyproject.toml`.** The bump is a human-authored
  commit that precedes the tag. This keeps the version declarative,
  reviewable, and visible at a glance in the file that everything
  else reads.
- **Does not commit back to `main`.** No bot commits, no "prepare next
  dev cycle" commits. `main` looks exactly like the release commit
  until the next release.
- **Does not generate a `CHANGELOG.md`.** Release notes live on the
  GitHub release page and are auto-categorized from merged PR labels
  (see `.github/release.yml`). If you want a tracked changelog file
  later, `release-drafter` or `release-please` are natural upgrades.
- **Does not lifecycle-manage the zoekt backend.** The image contains
  only the Python MCP server; users run the backend themselves via
  `deploy/docker-compose.yml`. This is a deliberate layering choice
  shared by `elastic/mcp-server-elasticsearch`,
  `github/github-mcp-server`, and most other first-party MCP servers.
- **Does not submit to MCP catalogs.** Listing on the
  [modelcontextprotocol.io](https://modelcontextprotocol.io) registry
  and [Docker MCP Catalog](https://hub.docker.com/mcp) is a separate
  follow-up once the first release is verified working end-to-end.

## Troubleshooting

**`verify-version` fails with "tag does not match pyproject.toml".**
You pushed a tag without bumping the version first, or you bumped but
forgot to push the bump commit along with the tag. Delete the tag on
origin (`git push origin :refs/tags/v0.2.0`) and locally
(`git tag -d v0.2.0`), then rerun `./scripts/release.sh 0.2.0`.

**`publish-pypi` fails with "no pending publisher found".**
Trusted Publishing is not configured on PyPI yet. Complete
[one-time setup step 1](#1-register-the-pypi-trusted-publisher), then
re-run the job from the Actions UI — no need to re-tag.

**`publish-pypi` fails with "environment pypi not found".**
The GitHub `pypi` environment does not exist. Complete
[one-time setup step 2](#2-create-the-github-pypi-environment), then
re-run the job.

**`publish-ghcr` succeeds but `docker pull` requires authentication.**
The package is still private. Complete
[one-time setup step 3](#3-make-the-ghcr-package-public-after-the-first-publish).

**`create-release` fails with "file not found".**
One of the attached assets (`deploy/docker-compose.yml` or
`deploy/index.sh`) is missing from the checkout. Either the file was
moved or the checkout action is targeting the wrong ref. Usually
means a file was renamed without updating `release.yml`.

**I need to yank a release.**
On PyPI: `pip index versions zoekt-mcp` → find the version →
[yank via the project page](https://pypi.org/help/#yanked). On
`ghcr.io`: delete the affected tag from the package page. On GitHub:
delete the release and its tag. There is no single-command "un-cut"
— releases are meant to be additive.
