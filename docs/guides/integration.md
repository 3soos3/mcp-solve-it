# Integration Guide

This guide shows how to integrate the SOLVE-IT MCP Server with common MCP clients.

## Prerequisites

Before configuring any client:

1. Install the server: `pip install -e .` from the project root
2. Set `solveit_data_path` in `config/default.toml` to an **absolute** path pointing at your SOLVE-IT repository root
3. Verify the server starts correctly: `python -m mcp_chassis --config /absolute/path/to/config/default.toml`

Always use absolute paths in client configurations — MCP clients may launch the server from an arbitrary working directory.

## MCP Clients

### Claude Code

Add to your project's `.mcp.json` file:

```json
{
  "mcpServers": {
    "solveit": {
      "type": "stdio",
      "command": "python3",
      "args": [
        "-m", "mcp_chassis",
        "--config", "/absolute/path/to/mcp-solve-it/config/default.toml"
      ]
    }
  }
}
```

Alternatively, use `run.py` if the package is not installed:

```json
{
  "mcpServers": {
    "solveit": {
      "type": "stdio",
      "command": "python3",
      "args": [
        "/absolute/path/to/mcp-solve-it/run.py",
        "--config",
        "/absolute/path/to/mcp-solve-it/config/default.toml"
      ]
    }
  }
}
```

Claude Code will start the server automatically when you open the project. You can then ask questions like:

- "What SOLVE-IT tools are available?"
- "Search for techniques related to disk imaging"
- "What weaknesses affect DFT-1001?"

### Claude Desktop

Add to `claude_desktop_config.json`:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux**: `~/.config/claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "solveit": {
      "command": "python3",
      "args": [
        "-m", "mcp_chassis",
        "--config", "/absolute/path/to/mcp-solve-it/config/default.toml"
      ]
    }
  }
}
```

Restart Claude Desktop after saving. The server will start automatically when Claude Desktop launches.

### Other MCP Clients (stdio)

Any MCP client that supports stdio transport can use this server. The general pattern is:

```json
{
  "mcpServers": {
    "solveit": {
      "command": "python3",
      "args": [
        "-m", "mcp_chassis",
        "--config", "/absolute/path/to/mcp-solve-it/config/default.toml"
      ]
    }
  }
}
```

Substitute `python3` with the appropriate Python interpreter path for your system if needed (e.g. from a virtual environment: `/path/to/venv/bin/python`).

### HTTP Transport

For web clients or scenarios requiring HTTP access, enable HTTP transport:

```toml
[server]
transport = "http"
```

Or use the environment variable:

```bash
MCP_TRANSPORT=http python -m mcp_chassis --config config/default.toml
```

When HTTP transport is active, the server exposes:

- MCP JSON-RPC endpoint over HTTP (port 8000 by default)
- `GET /health` — health probe (only available with HTTP transport)

To change the port, set `MCP_HTTP_PORT` or configure it in the `[server]` section of TOML.

!!! note "HTTP transport is a stub"
    The HTTP transport in this release is a stub — it provides the `/health` endpoint but full HTTP/SSE MCP support is not yet implemented. Use stdio transport for production MCP client connections.

## Environment Variable Overrides

The following environment variables can override settings in `config/default.toml` at runtime. These are useful for Docker or CI environments where you don't want to modify the config file.

| Variable | Overrides |
|---|---|
| `MCP_CHASSIS_CONFIG` | Path to the config file |
| `MCP_TRANSPORT` | `[server] transport` |
| `MCP_LOG_LEVEL` | `[server] log_level` |
| `MCP_SECURITY_PROFILE` | `[security] profile` |
| `MCP_RATE_LIMIT_ENABLED` | `[security.rate_limits] enabled` |
| `MCP_APP_SOLVEIT_DATA_PATH` | `[app] solveit_data_path` |
| `MCP_APP_OBJECTIVE_MAPPING` | `[app] objective_mapping` |
| `MCP_APP_ENABLE_EXTENSIONS` | `[app] enable_extensions` |
| `MCP_APP_INIT_REQUIRED` | `[app] init_required` |
| `MCP_APP_ENABLE_FULL_DETAIL_TOOLS` | `[app] enable_full_detail_tools` |

See [Environment Variables](../reference/environment-variables.md) for the complete reference.

## Using a Virtual Environment

If you installed the server in a virtual environment, point the client at the interpreter inside that environment:

```json
{
  "mcpServers": {
    "solveit": {
      "command": "/path/to/venv/bin/python",
      "args": [
        "-m", "mcp_chassis",
        "--config", "/absolute/path/to/mcp-solve-it/config/default.toml"
      ]
    }
  }
}
```

This avoids dependency conflicts with other Python projects on the same machine.

## Troubleshooting Integration Issues

### Tools not appearing in the client

1. Verify the server starts correctly on its own:
   ```bash
   python -m mcp_chassis --config /path/to/config/default.toml --log-level DEBUG 2>&1 | head -30
   ```
2. Confirm `solveit_data_path` in the TOML is an absolute path
3. Restart your MCP client completely
4. Check for JSON syntax errors in the client config file

### Server exits immediately

Check whether the config file is being found:

```bash
MCP_CHASSIS_CONFIG=/absolute/path/to/config/default.toml python -m mcp_chassis
echo "Exit code: $?"
```

A non-zero exit code indicates the server failed to start. Run with `--log-level DEBUG` to see the error.

### KB not loading

If `solveit_status` is the only tool available, the knowledge base did not load. See [Troubleshooting — Issue S1](troubleshooting.md#issue-s1-knowledge-base-fails-to-load-at-startup) for causes and fixes.

## Next Steps

- [Environment Variables](../reference/environment-variables.md) — all configuration options
- [Troubleshooting](troubleshooting.md) — common issues
- [Docker Deployment](../deployment/docker.md) — running in a container
