# Getting Started

This guide will get the SOLVE-IT MCP Server running on your machine.

## Prerequisites

- Python 3.11 or later
- The [SOLVE-IT repository](https://github.com/SOLVE-IT-DF/solve-it) cloned locally

## Installation

### 1. Clone the SOLVE-IT Knowledge Base

```bash
git clone https://github.com/SOLVE-IT-DF/solve-it.git
```

Note the full path to the cloned directory — you will need it in the configuration step.

### 2. Clone and Install the MCP Server

```bash
git clone https://github.com/3soos3/mcp-solve-it.git
cd mcp-solve-it
pip install -e ".[dev]"
```

This installs the `mcp_chassis` package in editable mode along with development dependencies. The minimum runtime dependencies are:

```bash
pip install "mcp>=1.2.0,<2.0"
```

## Configuration

All server settings live in `config/default.toml`. Open it and set `solveit_data_path` to the root of your cloned SOLVE-IT repository (the directory containing `data/` and `solve_it_library/`):

```toml
[app]
solveit_data_path = "/absolute/path/to/solve-it"
```

Using an absolute path avoids ambiguity when the server is launched from a different working directory (as MCP clients often do).

### Full Configuration Walkthrough

```toml
[server]
name = "solveit-mcp"
version = "0.1.0"
transport = "stdio"      # "stdio" (default) or "http"
log_level = "INFO"

[security]
profile = "moderate"     # "strict", "moderate", or "permissive"

[security.rate_limits]
enabled = true
global_rpm = 120
per_tool_rpm = 60
burst_size = 10

[security.io_limits]
max_request_size = 5000000    # 5 MB
max_response_size = 10000000  # 10 MB

[security.input_validation]
enabled = true
max_string_length = 10000
max_array_length = 100
max_object_depth = 10

[security.input_sanitization]
enabled = true
level = "moderate"  # "strict", "moderate", or "permissive"

[security.auth]
enabled = false
provider = "none"

[extensions]
auto_discover = true
init_module = "mcp_chassis.extensions.solveit_init"

[diagnostics]
health_check_enabled = true
include_config_summary = false

[app]
# Path to the SOLVE-IT repository root (absolute or relative to CWD)
solveit_data_path = "/path/to/solve-it"

# Objective mapping file (must exist in the SOLVE-IT data/ directory)
objective_mapping = "solve-it.json"

# Whether to load SOLVE-IT-X extension data
enable_extensions = true

# Exit on KB load failure (true) or start in degraded mode (false)
init_required = true

# Enable full-detail listing tools (large payloads, disabled by default)
enable_full_detail_tools = false

[app.search]
enable_item_types_filter = true
enable_substring_match = true
enable_search_logic = true
```

### Key Settings

**`solveit_data_path`** — Path to the cloned SOLVE-IT repository root. The server adds this path to `sys.path` at startup so it can import `solve_it_library`.

**`objective_mapping`** — Filename of the JSON mapping that categorizes techniques into forensic objectives. Must exist inside `<solveit_data_path>/data/`. The default `solve-it.json` reflects the official categorization.

**`enable_extensions`** — When `true`, the server loads any SOLVE-IT-X extension datasets found in the repository.

**`init_required`** — When `true` (default), the server exits with a clear error if the knowledge base fails to load. When `false`, the server starts in degraded mode with only `solveit_status` available. Set to `false` during development if you need to test server behavior without valid KB data.

**`enable_full_detail_tools`** — Controls whether three additional tools (`solveit_list_techniques_full_detail`, `solveit_list_weaknesses_full_detail`, `solveit_list_mitigations_full_detail`) are registered. These tools return the complete dataset for an item type and may consume a significant portion of an LLM's context window. If you enable them, also raise the response size limit:

```toml
[security.io_limits]
max_response_size = 20971520   # 20 MB
```

**`[app.search]` flags** — Each flag controls whether the corresponding parameter appears in the `solveit_search` tool schema. When a flag is `false`, the parameter is hidden and its default value is applied: `item_types` defaults to all types, `substring_match` defaults to `false`, `search_logic` defaults to `"AND"`.

### Security Profiles

The `[security] profile` key selects a baseline configuration:

| Profile | Rate Limit | I/O Limits | Sanitization | Error Detail |
|---|---|---|---|---|
| `strict` | 60 rpm global, 30 rpm/tool | 1 MB req, 5 MB resp | Full (path traversal, shell metachars, control chars) | Generic |
| `moderate` | 120 rpm global, 60 rpm/tool | 5 MB req, 20 MB resp | Path traversal + control chars | Detailed |
| `permissive` | Disabled | 50 MB req/resp | Null bytes only | Detailed |

Individual settings in `[security.rate_limits]`, `[security.io_limits]`, etc. override the profile defaults. The active profile can also be overridden at runtime with `MCP_SECURITY_PROFILE`.

### Transport

The default transport is `stdio`, which is correct for desktop MCP clients. To use HTTP transport:

```toml
[server]
transport = "http"
```

Or set the environment variable:

```bash
MCP_TRANSPORT=http python -m mcp_chassis --config config/default.toml
```

HTTP transport enables the `GET /health` endpoint.

## Running the Server

### From the Project Root

```bash
python -m mcp_chassis --config config/default.toml
```

### Using run.py

The project includes a `run.py` launcher that sets up the Python path automatically. This is useful when the package is not installed:

```bash
python run.py --config config/default.toml
```

### Verifying Startup

Successful startup logs look like:

```
INFO  SOLVE-IT KB loaded: 120 techniques, 85 weaknesses, 60 mitigations
      (path: /path/to/solve-it, mapping: solve-it.json, extensions: true)
```

If the KB fails to load and `init_required = true`, the server will exit with a clear error message. See [Troubleshooting](guides/troubleshooting.md) for common causes.

## Connecting from Claude Code

Add to your project's `.mcp.json`:

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

Or, if the package is installed with `pip install -e .`:

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

## Connecting from Claude Desktop

Add to `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "solveit": {
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

Always use absolute paths for both the script and the config file so the server works regardless of what directory Claude Desktop launches it from.

Restart Claude Desktop after saving the config. You can then ask questions like:

- "What SOLVE-IT tools are available?"
- "Search for techniques related to memory acquisition"
- "What weaknesses affect DFT-1001?"

## Next Steps

- [Tools Overview](reference/tools-overview.md) — all available tools and their parameters
- [For Forensic Analysts](guides/for-forensic-analysts.md) — investigation workflows
- [Integration Guide](guides/integration.md) — other MCP clients and options
- [Troubleshooting](guides/troubleshooting.md) — common setup issues
