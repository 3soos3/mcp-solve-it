# Architecture Overview

How the SOLVE-IT MCP Server is structured, how it starts up, and how requests flow through it.

## System Diagram

```
┌─────────────────────────────────────────────────────┐
│                  MCP Client (stdio)                  │
└──────────────────────┬──────────────────────────────┘
                       │ JSON-RPC over stdin/stdout
┌──────────────────────▼──────────────────────────────┐
│               MCP Chassis Framework                  │
│  ┌──────────────────────────────────────────────┐   │
│  │          Security Middleware Pipeline         │   │
│  │  I/O Limits → Auth → Rate Limit →            │   │
│  │  Sanitize → Validate                         │   │
│  └──────────────────────┬───────────────────────┘   │
│  ┌──────────────────────▼───────────────────────┐   │
│  │           ChassisServer._dispatch_tool()      │   │
│  └──────────────────────┬───────────────────────┘   │
└─────────────────────────┼───────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────┐
│               SOLVE-IT Extension Layer               │
│  ┌───────────────────┐  ┌──────────────────────┐    │
│  │  solveit_init.py  │  │  solveit_tools.py    │    │
│  │  (init hook)      │  │  (tool handlers)     │    │
│  └─────────┬─────────┘  └──────────┬───────────┘    │
│            │                       │                 │
│  ┌─────────▼───────────────────────▼───────────┐    │
│  │              KnowledgeBase                   │    │
│  │         (SOLVE-IT library, read-only)        │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

## Startup Sequence

The chassis processes startup in this order:

```
1. config/default.toml loaded by MCP Chassis
   ├── [server] — transport, log level
   ├── [security] — profile and overrides
   ├── [extensions] — auto_discover, init_module
   └── [app] — SOLVE-IT-specific settings

2. Init hook runs: solveit_init.py → on_init(server)
   a. Reads [app] config section
   b. Applies MCP_APP_* environment variable overrides
   c. Validates config into SolveItAppConfig dataclass
   d. Resolves solveit_data_path to an absolute path
   e. Adds resolved path to sys.path
   f. Imports solve_it_library.KnowledgeBase
   g. Instantiates KnowledgeBase with data path, mapping, and extension flag
   h. On success: attaches KB to server._kb, sets server._kb_error = None
   i. On failure:
      - Sets server._kb = None, server._kb_error = "<message>"
      - If init_required = true: exits with code 1
      - If init_required = false: continues (degraded mode)

3. Extension auto-discovery scans extensions/tools/
   └── finds solveit_tools.py → calls register(server)

4. solveit_tools.py register(server)
   a. Always registers: solveit_status (1)
   b. If server._kb is None: exits register() — only status tool available
   c. If server._kb is loaded:
      - Batch tools via register_simple_tools (8)
      - Relationship tools, manual registration (5)
      - Search tool (1)
      - Extension info tool (1)
      - Citation tools (2)
      - Full-detail tools if enable_full_detail_tools = true (0 or 3)

5. Chassis diagnostics registers __health_check (1)

6. Server enters stdio event loop
```

The init hook runs **before** extension discovery, so `server._kb` is available when `solveit_tools.py` calls `register()`.

## Request Flow

```
MCP Client
  → stdin → stdio transport → MCP SDK → ChassisServer._dispatch_tool()
  → Security Middleware Pipeline:
      1. I/O limit check (request size)
      2. Auth check
      3. Rate limit check
      4. Input sanitization
      5. Input validation against JSON schema
  → Tool Handler (in solveit_tools.py)
  → KnowledgeBase method call (read-only)
  → JSON response
  → stdout → MCP Client
```

The middleware pipeline is applied before every handler invocation. SOLVE-IT tools do not modify or bypass it.

## Key Components

### ChassisServer (`server.py`)

The central orchestrator. Manages tool registration, the middleware pipeline, transport, and the `_dispatch_tool()` method that routes incoming requests. SOLVE-IT attaches its `KnowledgeBase` instance to `server._kb` during the init hook.

### Configuration (`config.py`)

Loads `config/default.toml` into a typed dataclass hierarchy. The `[app]` section is left as a raw dict and passed to the init hook for SOLVE-IT-specific parsing.

### Init Hook (`solveit_init.py`)

Runs once at startup before extension discovery. Responsible for:
- Parsing and validating `[app]` config into `SolveItAppConfig`
- Applying `MCP_APP_*` environment variable overrides
- Loading the SOLVE-IT `KnowledgeBase`
- Attaching the KB to `server._kb`
- Enforcing `init_required` — exit or continue in degraded mode

### Tool Extension (`solveit_tools.py`)

Discovered automatically by the chassis from `extensions/tools/`. Registers all SOLVE-IT tools against `server`. Uses two registration mechanisms:

**Batch registration** (`register_simple_tools`): 8 tools with uniform input schema and handler patterns — lookups and listings.

**Manual registration**: 13 tools requiring non-uniform handling:
- 5 relationship tools — ID validation before KB call
- 1 search tool — schema varies based on `[app.search]` config flags
- 0 or 3 full-detail tools — config-gated by `enable_full_detail_tools`
- 1 status tool — always registered, handles `server._kb = None`
- 1 extension info tool — accesses extension metadata
- 2 citation tools — custom response shaping

### Security Middleware Pipeline (`middleware/pipeline.py`)

Runs in this order for every request:

1. **I/O limits** — enforce `max_request_size` / `max_response_size`
2. **Auth** — token check (disabled for stdio transport)
3. **Rate limit** — per-tool and global request-per-minute limits
4. **Sanitization** — strip path traversal sequences, shell metacharacters, control characters (level determined by active security profile)
5. **Validation** — enforce JSON schema, string length limits, array limits, object depth

### KnowledgeBase

The SOLVE-IT library (`solve_it_library.KnowledgeBase`) is the authoritative data source.

- Loaded once at startup — not reinstantiated per request
- Not pip-installable; the init hook adds the SOLVE-IT repository root to `sys.path` at runtime
- Read-only after construction — safe for concurrent calls
- Supports SOLVE-IT-X extension data when `enable_extensions = true`

### Transport (`transport/stdio.py`)

Default transport. Reads JSON-RPC messages from stdin, writes responses to stdout. All logging goes to stderr to avoid contaminating the JSON-RPC stream.

HTTP transport (`transport/http_stub.py`) is available but provides only the `/health` endpoint in this release.

## Configuration Flow

```
config/default.toml
  └── [app] → raw dict → on_init() → _apply_env_overrides() → SolveItAppConfig
                                          ↑
                                MCP_APP_* environment variables
```

`MCP_APP_*` variables are applied by the init hook before the raw dict is parsed into the typed config, so they override TOML values. The chassis-level variables (`MCP_TRANSPORT`, `MCP_SECURITY_PROFILE`, etc.) are applied by the chassis before the init hook runs.

## Security Design

Security is inherited entirely from the chassis middleware pipeline. SOLVE-IT tools do not extend or bypass it. The primary risk surface is malformed tool arguments — the pipeline handles these before handlers are reached.

All data access is read-only against the local KB. No external API calls or user-uploaded content is involved.

For profile configuration details, see the [Getting Started](../getting-started.md#security-profiles) guide. For troubleshooting sanitization or validation issues, see the [Troubleshooting](../guides/troubleshooting.md) guide.
