# syntax=docker/dockerfile:1.4
# Release Dockerfile for mcp-chassis (SOLVE-IT MCP Server) — Alpine Linux
# Multi-stage build for minimal image size and maximum security.
# SOLVE_IT_VERSION is always overridden with the release tag (e.g. v0.2025-10).
# Supports multi-architecture: linux/amd64, linux/arm64, linux/arm/v7

# ============================================================================
# Stage 1: Builder
# ============================================================================
FROM python:3.11-alpine AS builder

# Build args
ARG SOLVE_IT_VERSION=main
ARG SOLVE_IT_DATA_PATH=/app/solve-it-main/data
ARG SOLVE_IT_SHA=unknown
ARG MCP_VERSION=unknown

# Install build dependencies (removed in same layer via virtual group)
RUN apk add --no-cache --virtual .build-deps \
    build-base \
    libffi-dev \
    openssl-dev \
    git \
    cargo \
    rust

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy project definition for pip install
WORKDIR /build
COPY pyproject.toml README.md ./

# Fetch SOLVE-IT data at the specified release tag
RUN git clone --depth 1 --branch ${SOLVE_IT_VERSION} \
    https://github.com/SOLVE-IT-DF/solve-it.git /tmp/solve-it-main && \
    rm -rf /tmp/solve-it-main/.git

# Install package from pyproject.toml, then clean up
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir . && \
    # Cleanup to reduce venv size
    pip uninstall -y pip setuptools wheel 2>/dev/null || true && \
    find /opt/venv -type f -name '*.pyc' -delete && \
    find /opt/venv -type f -name '*.pyo' -delete && \
    find /opt/venv -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

# Remove build dependencies
RUN apk del .build-deps

# ============================================================================
# Stage 2: Runtime
# ============================================================================
FROM python:3.11-alpine AS runtime

# Build arguments
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION=release
ARG BUILD_DATE_RFC3339=${BUILD_DATE:-1970-01-01T00:00:00Z}
ARG SOLVE_IT_SHA=unknown
ARG SOLVE_IT_VERSION=unknown
ARG MCP_VERSION=unknown

# Metadata labels following OCI Image Spec
LABEL org.opencontainers.image.created="${BUILD_DATE_RFC3339}" \
      org.opencontainers.image.url="https://github.com/3soos3/mcp-solve-it" \
      org.opencontainers.image.documentation="https://github.com/3soos3/mcp-solve-it/blob/main/README.md" \
      org.opencontainers.image.source="https://github.com/3soos3/mcp-solve-it" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.title="SOLVE-IT MCP Server (mcp-chassis)" \
      org.opencontainers.image.description="MCP server providing LLM access to the SOLVE-IT Digital Forensics Knowledge Base" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.base.name="docker.io/library/python:3.11-alpine"

# Install minimal runtime dependencies and create non-root user
RUN apk add --no-cache \
        ca-certificates \
        libffi \
        openssl && \
    # Create non-root user for security (uid/gid 1000)
    addgroup -g 1000 mcpuser && \
    adduser -D -u 1000 -G mcpuser -h /home/mcpuser -s /bin/sh mcpuser && \
    chmod 750 /home/mcpuser && \
    # Runtime scratch directories
    mkdir -p /tmp/app-cache /tmp/app-tmp && \
    chown -R mcpuser:mcpuser /tmp/app-cache /tmp/app-tmp && \
    rm -rf /var/cache/apk/*

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source
COPY --chown=mcpuser:mcpuser src/ /app/src/

# Copy config directory (TOML-based configuration)
COPY --chown=mcpuser:mcpuser config/ /app/config/

# Copy SOLVE-IT data from builder (no git in runtime image)
COPY --from=builder --chown=mcpuser:mcpuser /tmp/solve-it-main /app/solve-it-main

USER mcpuser

# Environment variables with sensible defaults
# FORENSIC_METADATA=true: release images embed audit/compliance traceability
# metadata in tool responses.
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_CHASSIS_CONFIG=/app/config/default.toml \
    SOLVE_IT_DATA_PATH=/app/solve-it-main/data \
    MCP_TRANSPORT=http \
    HTTP_HOST=0.0.0.0 \
    HTTP_PORT=8000 \
    OTEL_ENABLED=true \
    ENVIRONMENT=production \
    LOG_LEVEL=INFO \
    LOG_FORMAT=json \
    TMPDIR=/tmp/app-tmp \
    IMAGE_TAG=${SOLVE_IT_SHA}-${MCP_VERSION} \
    MCP_VERSION=${MCP_VERSION} \
    SOLVE_IT_VERSION=${SOLVE_IT_VERSION} \
    FORENSIC_METADATA=true

EXPOSE 8000

# Health check using wget (available in Alpine, no curl needed)
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD if [ "$MCP_TRANSPORT" = "http" ]; then \
            wget --no-verbose --tries=1 --spider http://localhost:${HTTP_PORT}/healthz || exit 1; \
        else \
            exit 0; \
        fi

ENTRYPOINT ["python", "-m", "mcp_chassis"]
