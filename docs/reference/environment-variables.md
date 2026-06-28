# Environment Variables Reference

Environment variables that control the SOLVE-IT MCP Server. Variables can be set in the shell, in a Docker `-e` flag, or in a Kubernetes ConfigMap.

**Note:** Most settings are configured in `config/default.toml`. Environment variables provide runtime overrides — useful in Docker or CI environments where you don't want to modify the config file.

---

## Quick Reference

| Variable | Overrides | Default |
|---|---|---|
| [`MCP_CHASSIS_CONFIG`](#mcp_chassis_config) | Config file path | `config/default.toml` (CWD-relative) |
| [`MCP_LOG_LEVEL`](#mcp_log_level) | `[server] log_level` | `INFO` |
| [`MCP_TRANSPORT`](#mcp_transport) | `[server] transport` | `stdio` |
| [`MCP_SECURITY_PROFILE`](#mcp_security_profile) | `[security] profile` | `moderate` |
| [`MCP_RATE_LIMIT_ENABLED`](#mcp_rate_limit_enabled) | `[security.rate_limits] enabled` | `true` |
| [`MCP_APP_SOLVEIT_DATA_PATH`](#mcp_app_solveit_data_path) | `[app] solveit_data_path` | (none — must be set) |
| [`MCP_APP_OBJECTIVE_MAPPING`](#mcp_app_objective_mapping) | `[app] objective_mapping` | `solve-it.json` |
| [`MCP_APP_ENABLE_EXTENSIONS`](#mcp_app_enable_extensions) | `[app] enable_extensions` | `true` |
| [`MCP_APP_INIT_REQUIRED`](#mcp_app_init_required) | `[app] init_required` | `true` |
| [`MCP_APP_ENABLE_FULL_DETAIL_TOOLS`](#mcp_app_enable_full_detail_tools) | `[app] enable_full_detail_tools` | `false` |

Environment variables take precedence over TOML values when both are set.

---

## Chassis Variables

### `MCP_CHASSIS_CONFIG`

Path to the TOML configuration file.

| | |
|---|---|
| **Values** | Absolute or relative path to a `.toml` file |
| **Default** | Looks for `config/default.toml` relative to the current working directory |

```bash
MCP_CHASSIS_CONFIG=/absolute/path/to/config/default.toml python -m mcp_chassis
```

Use an absolute path to ensure the server finds the config regardless of the working directory it is launched from.

---

### `MCP_LOG_LEVEL`

Minimum log severity level.

| | |
|---|---|
| **Values** | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| **Default** | `INFO` (or the value of `[server] log_level` in TOML) |

```bash
MCP_LOG_LEVEL=DEBUG python -m mcp_chassis --config config/default.toml
```

All logs go to stderr. stdout is reserved for MCP JSON-RPC communication.

---

### `MCP_TRANSPORT`

Transport protocol used by the server.

| | |
|---|---|
| **Values** | `stdio`, `http` |
| **Default** | `stdio` (or the value of `[server] transport` in TOML) |

```bash
# stdio mode — for MCP clients that launch the server as a subprocess (Claude Desktop, Claude Code)
python -m mcp_chassis --config config/default.toml

# HTTP mode — enables /health endpoint
MCP_TRANSPORT=http python -m mcp_chassis --config config/default.toml
```

!!! note "HTTP transport is a stub"
    The HTTP transport in this release provides only the `/health` endpoint. Full HTTP/SSE MCP support is not yet implemented. Use `stdio` for all production MCP client connections.

---

## Security Variables

### `MCP_SECURITY_PROFILE`

Security profile baseline. Overrides `[security] profile` in TOML.

| | |
|---|---|
| **Values** | `strict`, `moderate`, `permissive` |
| **Default** | `moderate` |

| Profile | Rate Limit | I/O Limits | Sanitization | Error Detail |
|---|---|---|---|---|
| `strict` | 60 rpm global, 30 rpm/tool | 1 MB req, 5 MB resp | Full (path traversal, shell metachars, control chars) | Generic |
| `moderate` | 120 rpm global, 60 rpm/tool | 5 MB req, 20 MB resp | Path traversal + control chars | Detailed |
| `permissive` | Disabled | 50 MB req/resp | Null bytes only | Detailed |

Individual settings in `[security.*]` TOML sections override the profile defaults even when this variable is set.

```bash
# Development: disable rate limiting and use permissive sanitization
MCP_SECURITY_PROFILE=permissive python -m mcp_chassis --config config/default.toml
```

---

### `MCP_RATE_LIMIT_ENABLED`

Enable or disable rate limiting entirely.

| | |
|---|---|
| **Values** | `true`, `false`, `1`, `0`, `yes`, `no` |
| **Default** | `true` |

```bash
MCP_RATE_LIMIT_ENABLED=false python -m mcp_chassis --config config/default.toml
```

Useful during development or testing when rate limits interfere with rapid tool calls.

---

## SOLVE-IT Application Variables

These variables map to the `[app]` section of `config/default.toml`. They are applied by the `solveit_init.py` init hook before the TOML values are parsed into the typed config dataclass.

### `MCP_APP_SOLVEIT_DATA_PATH`

Path to the SOLVE-IT repository root.

| | |
|---|---|
| **Values** | Absolute path |
| **Default** | Value from `[app] solveit_data_path` in TOML |

```bash
MCP_APP_SOLVEIT_DATA_PATH=/data/solve-it python -m mcp_chassis --config config/default.toml
```

The init hook adds this path to `sys.path` so it can import `solve_it_library`. The path must point to the repository root — the directory containing both `data/` and `solve_it_library/`.

---

### `MCP_APP_OBJECTIVE_MAPPING`

Filename of the objective mapping JSON file.

| | |
|---|---|
| **Values** | Filename (not a full path) |
| **Default** | `solve-it.json` |

The file must exist inside `<solveit_data_path>/data/`. The default `solve-it.json` reflects the official SOLVE-IT categorization.

```bash
MCP_APP_OBJECTIVE_MAPPING=custom-mapping.json python -m mcp_chassis --config config/default.toml
```

---

### `MCP_APP_ENABLE_EXTENSIONS`

Whether to load SOLVE-IT-X extension datasets.

| | |
|---|---|
| **Values** | `true`, `false`, `1`, `0`, `yes`, `no` |
| **Default** | `true` |

```bash
MCP_APP_ENABLE_EXTENSIONS=false python -m mcp_chassis --config config/default.toml
```

---

### `MCP_APP_INIT_REQUIRED`

Whether to exit on KB load failure (`true`) or start in degraded mode (`false`).

| | |
|---|---|
| **Values** | `true`, `false`, `1`, `0`, `yes`, `no` |
| **Default** | `true` |

When `false`, the server starts with only `solveit_status` available (reporting the load failure). Set to `false` during development to test server behavior without valid KB data.

```bash
MCP_APP_INIT_REQUIRED=false python -m mcp_chassis --config config/default.toml
```

---

### `MCP_APP_ENABLE_FULL_DETAIL_TOOLS`

Whether to register the three full-detail listing tools.

| | |
|---|---|
| **Values** | `true`, `false`, `1`, `0`, `yes`, `no` |
| **Default** | `false` |

```bash
MCP_APP_ENABLE_FULL_DETAIL_TOOLS=true python -m mcp_chassis --config config/default.toml
```

!!! warning "Large payload tools"
    Full-detail tools return 25,000–32,000 tokens per call. When enabling them, also raise the response size limit in TOML:
    ```toml
    [security.io_limits]
    max_response_size = 20971520  # 20 MB
    ```

---

## Example Configurations

### Minimal local run (development)

```bash
MCP_SECURITY_PROFILE=permissive \
MCP_RATE_LIMIT_ENABLED=false \
MCP_APP_SOLVEIT_DATA_PATH=/path/to/solve-it \
python -m mcp_chassis --config config/default.toml
```

### Docker with environment overrides

```bash
docker run -i \
  -e MCP_CHASSIS_CONFIG=/app/config/default.toml \
  -e MCP_APP_SOLVEIT_DATA_PATH=/data/solve-it \
  -v /path/to/solve-it:/data/solve-it:ro \
  my-mcp-server
```

### Testing without SOLVE-IT data

```bash
MCP_APP_INIT_REQUIRED=false python -m mcp_chassis --config config/default.toml
```

The server starts with only `solveit_status` available, which reports the KB load failure. Useful for testing chassis behavior in isolation.
