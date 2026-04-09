# Releasing zoekt-mcp

This document covers **how** to cut a release. For the design rationale
(why declarative versioning, why multi-arch, why no auto-bump bot).

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
Six jobs run in this order:

```text
verify-version  ─┐
                 ├─▶  publish-pypi  ─┐
build-wheel  ────┤                    ├─▶  create-release ─▶ publish-mcp-registry
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
   (etc.) for prereleases. The image carries an
   `io.modelcontextprotocol.server.name` annotation that the MCP
   Registry uses to verify ownership of the `ghcr.io` artifact.
5. **`create-release`** waits for **both** publish jobs to succeed,
   then creates the GitHub release with auto-generated notes
   (categorized by `.github/release.yml`) and attaches
   `deploy/docker-compose.yml` + `deploy/index.sh` as release assets.
6. **`publish-mcp-registry`** runs last — only if everything above
   went green — and publishes the server to the
   [official MCP Registry](https://registry.modelcontextprotocol.io/)
   under the `io.github.radiovisual/zoekt-mcp` namespace.
   Authenticates via GitHub OIDC (no secrets required) and patches
   `server.json` version fields from the tag on the fly, so the git
   tag stays the single source of truth. Ownership is verified by
   the `mcp-name:` marker in `README.md` (which PyPI exposes as the
   project description) and the OCI annotation on the ghcr.io image.

If PyPI or GHCR fails, no GitHub release is created and the MCP
Registry publish never runs. Re-run the failed job from the Actions
UI once the underlying cause is fixed; downstream jobs re-run once
their dependencies go green.

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

# MCP Registry
curl -s "https://registry.modelcontextprotocol.io/v0.1/servers?search=zoekt-mcp" \
  | python3 -m json.tool
```

## Working with `server.json`

`server.json` at the repo root is the manifest the `publish-mcp-registry`
job sends to
[registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io/).
Most of it is static (name, description, env vars, package list) and
you edit it like any other file. A few things are non-obvious and
worth knowing before you touch it.

### The version fields are placeholders — leave them at `0.0.0`

Three fields in `server.json` encode the release version:

- `.version`
- `.packages[0].version` (the PyPI entry)
- `.packages[1].identifier` (the OCI entry — the version is inside
  the image tag, e.g. `ghcr.io/radiovisual/zoekt-mcp:0.3.0`)

The committed file keeps all three pinned at `0.0.0`. The
`publish-mcp-registry` job patches them on the fly from the git tag
(see the `jq` invocation in `.github/workflows/release.yml`) before
it calls `mcp-publisher publish`. This keeps the git tag as the
**single source of truth** for versioning — you never have to remember
to bump `server.json` alongside `pyproject.toml`.

Do not hand-bump the version fields. If you do, the CI patch step
will just overwrite your change.

### Description is hard-capped at 100 characters

The MCP Registry enforces `len(description) <= 100` server-side, and
this limit is NOT in the published JSON Schema — so `mcp-publisher
validate` only catches it because it POSTs the file to the live
registry (a schema-only validator would pass a 300-char description
and then fail at publish time). When you edit `.description`, count
characters before committing or run `mcp-publisher validate` locally.

### Validating locally

Install `mcp-publisher` once:

```bash
curl -L "https://github.com/modelcontextprotocol/registry/releases/latest/download/mcp-publisher_$(uname -s | tr '[:upper:]' '[:lower:]')_$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/').tar.gz" \
  | tar xz mcp-publisher
sudo mv mcp-publisher /usr/local/bin/
```

Then validate from the repo root whenever you edit the file:

```bash
mcp-publisher validate
```

This hits the live registry's validation endpoint, so it enforces
both the JSON Schema and the field-level constraints (length caps,
allowed enum values, registry-type rules) that the schema alone
doesn't capture.

### Validation also runs in CI on every PR

`.github/workflows/ci.yml` has a `validate-server-json` job that runs
the same `mcp-publisher validate` command on every push and pull
request. You can edit `server.json` without installing
`mcp-publisher` locally and let CI be the safety net — but the
feedback loop is obviously slower than running it yourself.

### Ownership verification is version-bound

Two markers prove this repo owns the published artifacts:

- **PyPI**: the literal string `mcp-name: io.github.radiovisual/zoekt-mcp`
  inside `README.md` (wrapped in an HTML comment at the bottom of the
  file). PyPI renders `README.md` as the project description, and the
  MCP Registry scans that page for this exact marker.
- **OCI**: the `io.modelcontextprotocol.server.name` annotation on the
  ghcr.io image manifest, set in the `publish-ghcr` job via
  `docker/metadata-action`'s `annotations:` block.

Both are tied to the *published artifact*, not to `main`. That means
if you remove either marker and cut a new release, the next publish
will fail ownership verification — even though main still looks fine
and `mcp-publisher validate` still passes. Be careful about editing
the README footer or the `publish-ghcr` labels/annotations block.

## What the workflow does NOT do

Called out explicitly so nobody spends time looking for it:

- **Does not bump `pyproject.toml`.** (unless you used the helper script)
  The bump is a human-authored commit that precedes the tag. This keeps the version declarative, reviewable, and visible at a glance in the file that everything
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
  shared by other MCP servers like `elastic/mcp-server-elasticsearch`,
  `github/github-mcp-server`, and most other first-party MCP servers.
- **Does not submit to the Docker MCP Catalog.** That's a separate
  PR against [`docker/mcp-registry`](https://github.com/docker/mcp-registry)
  and is explicitly out of scope — we list on
  [registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io/)
  (via `publish-mcp-registry`) and leave the Docker Hub catalog as an
  optional future follow-up.

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

**`publish-mcp-registry` fails with "Authentication failed".**
The `id-token: write` permission is missing from the job or the
`io.github.radiovisual/*` namespace doesn't match the workflow's
OIDC issuer (e.g. the repo was transferred). The namespace must be
`io.github.<owner>/...` where `<owner>` is the current GitHub owner
of this repository.

**`publish-mcp-registry` fails with "Package validation failed" on
the PyPI entry.** The MCP Registry scanned the PyPI project page and
couldn't find the `mcp-name: io.github.radiovisual/zoekt-mcp`
marker. Make sure that string (exactly, including the HTML comment
delimiters) is present in `README.md` on the released commit and
that `pyproject.toml` still sets `readme = "README.md"`. PyPI
renders the file as the project description, which is what the
registry scans.

**`publish-mcp-registry` fails with "Package validation failed" on
the OCI entry.** The pushed ghcr.io image doesn't carry the
`io.modelcontextprotocol.server.name` annotation. Check that
`publish-ghcr` passed both `labels:` AND `annotations:` to
`docker/build-push-action` (OCI annotations live on the image
manifest, separate from the labels on the image config) and that
the metadata-action `annotations:` block is intact.

**I need to yank a release.**
On PyPI: `pip index versions zoekt-mcp` → find the version →
[yank via the project page](https://pypi.org/help/#yanked). On
`ghcr.io`: delete the affected tag from the package page. On GitHub:
delete the release and its tag. There is no single-command "un-cut"
— releases are meant to be additive.
