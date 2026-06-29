# syntax=docker/dockerfile:1.4
# Unified Dockerfile for mcp-chassis (SOLVE-IT MCP Server) — Alpine Linux.
#
# SOLVE_IT_MODE controls the data strategy:
#   release  (default) — bake specific SOLVE-IT release tag; FORENSIC_METADATA=true
#   monthly            — bake SHA-pinned SOLVE-IT HEAD; FORENSIC_METADATA=false
#   live               — no data baked in; entrypoint fetches at startup
#
# Multi-architecture: linux/amd64, linux/arm64, linux/arm/v7

# ============================================================================
# Stage 1: Builder
# ============================================================================
FROM python:3.11-alpine AS builder

ARG SOLVE_IT_MODE=release
ARG SOLVE_IT_VERSION=main
ARG SOLVEIT_SHA=""
ARG MCP_VERSION=unknown

RUN apk add --no-cache --virtual .build-deps \
    build-base \
    libffi-dev \
    openssl-dev \
    git \
    cargo \
    rust

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY pyproject.toml README.md ./

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . && \
    pip uninstall -y pip setuptools wheel 2>/dev/null || true && \
    find /opt/venv -type f -name '*.pyc' -delete && \
    find /opt/venv -type f -name '*.pyo' -delete && \
    find /opt/venv -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

RUN apk del .build-deps

# Clone SOLVE-IT data for release/monthly modes.
# SHA checkout: reproducible (monthly/latest). Tag checkout: pinned release.
# Live mode: empty directory — entrypoint fills it at runtime.
RUN if [ "$SOLVE_IT_MODE" != "live" ]; then \
      git clone https://github.com/SOLVE-IT-DF/solve-it.git /tmp/solve-it-main; \
      if [ -n "$SOLVEIT_SHA" ]; then \
        git -C /tmp/solve-it-main checkout "$SOLVEIT_SHA"; \
      elif [ -n "$SOLVE_IT_VERSION" ] && [ "$SOLVE_IT_VERSION" != "main" ]; then \
        git -C /tmp/solve-it-main checkout "$SOLVE_IT_VERSION"; \
      fi; \
      rm -rf /tmp/solve-it-main/.git; \
    else \
      mkdir -p /tmp/solve-it-main; \
    fi

# ============================================================================
# Stage 2: Runtime
# ============================================================================
FROM python:3.11-alpine AS runtime

ARG SOLVE_IT_MODE=release
ARG FORENSIC_METADATA=true
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION=unknown
ARG SOLVEIT_SHA=unknown
ARG SOLVE_IT_VERSION=unknown
ARG MCP_VERSION=unknown

LABEL org.opencontainers.image.created="${BUILD_DATE:-1970-01-01T00:00:00Z}" \
      org.opencontainers.image.source="https://github.com/3soos3/solve-it-mcp-v2" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.title="SOLVE-IT MCP Server (chassis)" \
      org.opencontainers.image.description="MCP server for SOLVE-IT — mode: ${SOLVE_IT_MODE}" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.base.name="docker.io/library/python:3.11-alpine"

# wget + unzip only needed in live mode
RUN set -e; \
    EXTRA_PKGS=""; \
    if [ "$SOLVE_IT_MODE" = "live" ]; then EXTRA_PKGS="wget unzip"; fi; \
    apk add --no-cache ca-certificates libffi openssl $EXTRA_PKGS && \
    addgroup -g 1000 mcpuser && \
    adduser -D -u 1000 -G mcpuser -h /home/mcpuser -s /bin/sh mcpuser && \
    chmod 750 /home/mcpuser && \
    mkdir -p /tmp/app-cache/solve-it /tmp/app-tmp && \
    chown -R mcpuser:mcpuser /tmp/app-cache /tmp/app-tmp && \
    rm -rf /var/cache/apk/*

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY --chown=mcpuser:mcpuser src/ /app/src/
COPY --chown=mcpuser:mcpuser config/ /app/config/
COPY --chown=mcpuser:mcpuser docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Copy SOLVE-IT data (empty dir for live mode — entrypoint populates it)
COPY --from=builder --chown=mcpuser:mcpuser /tmp/solve-it-main /app/solve-it-main

USER mcpuser

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_CHASSIS_CONFIG=/app/config/default.toml \
    MCP_TRANSPORT=http \
    HTTP_HOST=0.0.0.0 \
    HTTP_PORT=8000 \
    MCP_OTEL_ENABLED=false \
    LOG_LEVEL=INFO \
    TMPDIR=/tmp/app-tmp \
    SOLVE_IT_MODE=${SOLVE_IT_MODE} \
    FORENSIC_METADATA=${FORENSIC_METADATA} \
    SOLVE_IT_VERSION=${SOLVE_IT_VERSION} \
    MCP_APP_SOLVEIT_DATA_PATH=/app/solve-it-main/data \
    SOLVE_IT_DATA_URL=https://data.solveit-df.org/solve-it-latest.zip \
    SOLVE_IT_DATA_DIR=/tmp/app-cache/solve-it

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=60s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider \
        http://localhost:${HTTP_PORT}/healthz 2>/dev/null || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
