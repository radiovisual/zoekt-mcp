# syntax=docker/dockerfile:1.7
#
# zoekt-mcp container image.
#
# This image ships ONLY the Python MCP server — a thin, versioned client
# that speaks zoekt-webserver's HTTP JSON API over stdio MCP. It does
# NOT bundle the zoekt backend (zoekt-webserver / zoekt-indexer); users
# run that themselves via the docker-compose.yml attached to every
# GitHub release, and point this container at it with the ZOEKT_URL
# environment variable.
#
# Build:
#     docker build -t zoekt-mcp .
#
# Run (backend on host, Linux):
#     docker run -i --rm --network=host \
#         -e ZOEKT_URL=http://localhost:6070 \
#         zoekt-mcp
#
# Run (backend on host, Docker Desktop mac/windows):
#     docker run -i --rm \
#         -e ZOEKT_URL=http://host.docker.internal:6070 \
#         zoekt-mcp
#
# MCP clients spawn this with stdio attached, so `-i` is required.

# ---------------------------------------------------------------------
# Stage 1: build the wheel with uv.
#
# uv is only needed at build time — it resolves against uv.lock and
# produces a wheel we can drop into a minimal runtime image.
# ---------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /build

# Copy just the files hatchling needs to build the wheel. Keeping this
# minimal improves layer caching: source edits don't bust the lockfile
# layer and vice versa.
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src/ ./src/

# Build the wheel into /build/dist. We intentionally don't `uv sync`
# here — we only need the wheel artifact, which `uv build` produces
# against pyproject.toml directly.
RUN uv build --wheel --out-dir /build/dist

# ---------------------------------------------------------------------
# Stage 2: minimal runtime.
#
# python:3.12-slim-bookworm keeps the image small while leaving a real
# shell in place for `docker exec` debugging. MCP servers run over
# stdio, so there's no port to health-check.
# ---------------------------------------------------------------------
FROM python:3.12-slim-bookworm

# OCI labels for ghcr.io package metadata. source / description get
# overridden by docker/metadata-action at release time, but the
# defaults here keep local builds self-describing.
LABEL org.opencontainers.image.title="zoekt-mcp" \
      org.opencontainers.image.description="MCP server exposing Sourcegraph Zoekt code search to AI agents" \
      org.opencontainers.image.source="https://github.com/radiovisual/zoekt-mcp" \
      org.opencontainers.image.licenses="MIT"

# Non-root runtime user. UID is fixed so bind mounts (if any) behave
# predictably across hosts. No login shell, no home directory.
RUN groupadd --system --gid 10001 zoekt \
 && useradd  --system --uid 10001 --gid zoekt --no-create-home \
             --shell /usr/sbin/nologin zoekt

# Install the wheel system-wide. pip is already present in the slim
# image; we remove the wheel file and pip cache to keep the layer tight.
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl \
 && rm -f /tmp/*.whl

USER zoekt

# Sensible default that matches the Python-side default in config.py.
# Override at run time with `-e ZOEKT_URL=...`.
ENV ZOEKT_URL=http://localhost:6070

# ENTRYPOINT rather than CMD so users can append extra flags:
#     docker run ... zoekt-mcp --timeout 60
ENTRYPOINT ["zoekt-mcp"]
