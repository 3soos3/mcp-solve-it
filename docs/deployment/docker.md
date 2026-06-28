# Docker Deployment

This guide covers building and running the SOLVE-IT MCP Server with Docker.

## Overview

The server is designed primarily for stdio transport, making Docker suitable for:

- Packaging the server with its Python dependencies for portable deployment
- Running in CI pipelines
- Isolating the server from the host Python environment
- Attaching SOLVE-IT data via a volume mount

## Dockerfile

The project includes a `Dockerfile` that uses a two-stage build:

1. **Builder stage** — installs the `mcp_chassis` package and its dependencies
2. **Runtime stage** — minimal Python image with the installed packages and config

```dockerfile
# Stage 1: install dependencies
FROM python:3.11-slim AS builder
WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .

# Stage 2: minimal runtime image
FROM python:3.11-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends procps net-tools curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY config/ config/

ENV MCP_CHASSIS_CONFIG=/app/config/default.toml

USER appuser

ENTRYPOINT ["python", "-m", "mcp_chassis"]
```

Key design decisions:

- The runtime image does **not** include the SOLVE-IT data — the data must be mounted at runtime via a Docker volume
- `MCP_CHASSIS_CONFIG` points to the bundled config at `/app/config/default.toml` inside the container
- The server runs as a non-root user (`appuser`)
- The entrypoint uses `python -m mcp_chassis`, so you can pass additional flags (e.g. `--log-level DEBUG`) as `docker run` arguments

## Building the Image

```bash
cd /path/to/mcp-solve-it
docker build -t mcp-solve-it:local .
```

## Running with Volume-Mounted SOLVE-IT Data

The SOLVE-IT data must be mounted into the container and `solveit_data_path` must point to the mount location.

### Method 1: Override via environment variable

```bash
docker run -i \
  -v /path/to/solve-it:/data/solve-it:ro \
  -e MCP_APP_SOLVEIT_DATA_PATH=/data/solve-it \
  mcp-solve-it:local
```

The `-i` flag is required — MCP servers communicate over stdin/stdout and need an interactive pipe.

### Method 2: Mount a custom config

Edit your `config/default.toml` to use a path that matches the container's mount point:

```toml
[app]
solveit_data_path = "/data/solve-it"
```

Then mount both the data and the config:

```bash
docker run -i \
  -v /path/to/solve-it:/data/solve-it:ro \
  -v /path/to/my-config.toml:/app/config/default.toml:ro \
  mcp-solve-it:local
```

## Docker Compose

For local development or persistent deployments:

```yaml
services:
  solveit-mcp:
    build: .
    image: mcp-solve-it:local
    stdin_open: true          # Required for MCP stdio transport
    tty: false
    volumes:
      - /path/to/solve-it:/data/solve-it:ro
    environment:
      - MCP_APP_SOLVEIT_DATA_PATH=/data/solve-it
      - MCP_LOG_LEVEL=INFO
    restart: unless-stopped
```

```bash
docker compose up
```

### HTTP Transport Variant

For HTTP mode (exposes the `/health` endpoint):

```yaml
services:
  solveit-mcp:
    build: .
    image: mcp-solve-it:local
    ports:
      - "8000:8000"
    volumes:
      - /path/to/solve-it:/data/solve-it:ro
    environment:
      - MCP_TRANSPORT=http
      - MCP_APP_SOLVEIT_DATA_PATH=/data/solve-it
      - MCP_LOG_LEVEL=INFO
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 3s
      retries: 3
      start_period: 15s
    restart: unless-stopped
```

!!! note "HTTP transport is a stub"
    The HTTP transport in this release provides only the `/health` endpoint. For MCP client connections, use stdio transport.

## Connecting an MCP Client to a Docker Container

### Claude Desktop or Claude Code (stdio)

Configure the client to run the container directly:

```json
{
  "mcpServers": {
    "solveit": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "/path/to/solve-it:/data/solve-it:ro",
        "-e", "MCP_APP_SOLVEIT_DATA_PATH=/data/solve-it",
        "mcp-solve-it:local"
      ]
    }
  }
}
```

The MCP client starts a new container for each session and removes it when the session ends (`--rm`).

## Security

The container runs as a non-root user (`appuser`, UID 1000). For additional hardening:

```bash
docker run -i \
  --security-opt=no-new-privileges:true \
  --cap-drop=ALL \
  --read-only \
  --tmpfs /tmp \
  -v /path/to/solve-it:/data/solve-it:ro \
  -e MCP_APP_SOLVEIT_DATA_PATH=/data/solve-it \
  mcp-solve-it:local
```

The SOLVE-IT data volume is mounted read-only (`:ro`). The `--read-only` flag makes the container filesystem read-only, requiring `--tmpfs /tmp` for any temporary files.

## Troubleshooting

### Container exits immediately

```bash
docker logs <container-id>
```

Common causes:
- No stdin attached — add `-i`
- `solveit_data_path` inside the container points to a path that does not exist — check the volume mount
- `init_required = true` and KB failed to load — see the log for `Failed to load SOLVE-IT KB`

### Checking the config inside the container

```bash
docker run --rm --entrypoint="" mcp-solve-it:local \
  cat /app/config/default.toml
```

### Startup with debug logging

```bash
docker run -i \
  -v /path/to/solve-it:/data/solve-it:ro \
  -e MCP_APP_SOLVEIT_DATA_PATH=/data/solve-it \
  mcp-solve-it:local \
  --log-level DEBUG
```

## Next Steps

- [Kubernetes Deployment](kubernetes.md) — running in a cluster with volume mounts for SOLVE-IT data
- [Environment Variables](../reference/environment-variables.md) — all configuration options
- [Getting Started](../getting-started.md) — non-Docker setup
