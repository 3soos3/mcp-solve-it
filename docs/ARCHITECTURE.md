# Architecture — SOLVE-IT MCP Server

## 1. Overview

The SOLVE-IT MCP Server provides programmatic access to the SOLVE-IT digital forensics knowledge base via the Model Context Protocol. It is built on the MCP Chassis framework, which supplies the transport layer, security middleware pipeline, configuration management, and extension auto-discovery. SOLVE-IT-specific logic lives entirely in the init hook and the single extension module.

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

---

## 2. Startup Sequence

```
1. config/default.toml loaded by MCP Chassis
2. solveit_init.py (init hook) runs
   a. Reads [app] config section (with MCP_APP_* env var overrides)
   b. Resolves solveit_data_path
   c. Adds SOLVE-IT library directory to sys.path
   d. Instantiates KnowledgeBase
   e. Attaches instance to server._kb
   f. Computes KB version CAI (sha2-256 hash of all JSON files) → server._kb_version_id
   g. Stores SOLVE_IT_VERSION env var → server._kb_version
3. Extension discovery scans extensions/tools/
   → finds solveit_tools.py
4. solveit_tools.py register(server) runs
   a. Always registers: status tool (1)
   b. If KB loaded successfully:
      - Orientation tool (1)
      - Batch tools via register_simple_tools (8)
      - Relationship tools, manual registration (6)
      - Objective/mapping tools (3)
      - Search tool (1)
      - Full-detail tools if config-gated flag enabled (0 or 3)
      - Extension info tool (1)
      - Citation tools (3)
```

The init hook runs before extension discovery, so `server._kb` is available when `solveit_tools.py` calls `register()`. If the KB fails to load, the status tool still registers and reports the failure; all other tools are skipped.

---

## 3. Request Flow

```
Client → transport (stdio or HTTP) → MCP SDK → ChassisServer._dispatch_tool()
  → FSS context vars set (transaction_id, parameters_cai)
  → Middleware Pipeline (Replay → I/O limits → Auth → Rate limit → Sanitize → Validate)
  → Tool Handler (in solveit_tools.py)
  → KnowledgeBase method call
  → result_cai computed → _provenance record built → embedded in response
  → JSON response → transport
```

The middleware pipeline is applied before every handler invocation. SOLVE-IT tools do not modify or bypass it. Every successful tool response includes a `_provenance` block with the full FSS-0004 §3.1 provenance record (transaction ID, CAI digests, KB version, timestamps, and optional Ed25519 signature). Error responses include `_provenance` with `evidentiary_status: non-evidentiary`.

---

## 4. Tool Registration

Tools are registered in `solveit_tools.py` via two mechanisms.

### Batch registration (register_simple_tools)

Eight tools are registered through the chassis batch helper:

- `solveit_get_technique`, `solveit_get_weakness`, `solveit_get_mitigation` — ID lookups
- `solveit_list_techniques`, `solveit_list_weaknesses`, `solveit_list_mitigations` — concise listings
- `solveit_list_objectives`, `solveit_get_techniques_for_objective` — objective tools

### Manual registration

Sixteen tools are registered individually:

| Group | Count | Reason for manual registration |
|---|---|---|
| Orientation tool | 1 | Assembles KB stats at call time |
| Relationship tools | 6 | ID validation before KB call; includes cross-traversal shortcut |
| Objective/mapping tools | 3 | Reverse lookup + framework switching |
| Search tool | 1 | Input schema varies based on `[app.search]` config flags |
| Full-detail tools | 0 or 3 | Config-gated; registered when `enable_full_detail_tools = true` |
| Status tool | 1 | Always registered, even when KB fails to load |
| Extension info tool | 1 | Registered only when KB loads |
| Citation tools | 3 | `get`, `list`, and inline `resolve` |

Total tools exposed: 24 always-registered + 3 config-gated full-detail = 27 maximum.

---

## 5. Knowledge Base

The SOLVE-IT library is the authoritative source of forensics knowledge used by all tools.

- Loaded once at startup in the init hook (`solveit_init.py`)
- Not pip-installable — the library directory is added to `sys.path` at runtime using the resolved `solveit_data_path`
- Exposes a `KnowledgeBase` class with methods for lookups, listings, relationship traversal, and search
- Read-only and deterministic — no internal state changes after construction, making it safe for concurrent tool calls
- Supports SOLVE-IT-X extension data; enabled via `enable_extensions = true` in `[app]`

The KB instance is stored on `server._kb` and accessed directly by tool handlers in `solveit_tools.py`.

---

## 6. Configuration

All SOLVE-IT-specific settings live in the `[app]` section of `config/default.toml`. The chassis `[server]`, `[security]`, and `[extensions]` sections are inherited unchanged.

```toml
[app]
solveit_data_path = "../solve-it/solve-it-main"
objective_mapping = "solve-it.json"
enable_extensions = true                          # SOLVE-IT-X data
enable_full_detail_tools = false                  # gates 3 additional tools

[app.search]
enable_item_types_filter = true
enable_substring_match = true
enable_search_logic = true
```

`[app]` settings can be overridden by `MCP_APP_*` environment variables (e.g. `MCP_APP_SOLVEIT_DATA_PATH`). New FSS-related env vars are also available at the chassis level:

| Variable | Purpose |
|---|---|
| `MCP_AUTH_MODE` | Auth mode: `none` (default), `apikey`, `oauth` |
| `MCP_REPLAY_WINDOW_SECONDS` | Replay prevention window in seconds (default 300, HTTP only) |
| `MCP_SECURITY_LOG_PATH` | Path for dedicated security event log (default: stderr) |
| `FSS_SIGNING_KEY_PATH` | PEM file path for Ed25519 provenance signing |
| `FSS_SIGNING_KEY_B64` | Base64-encoded raw signing key (alternative to PATH) |
| `SOLVE_IT_VERSION` | KB version label embedded in `_provenance` blocks |
| `MCP_OTEL_ENABLED` | Set `true` to enable OpenTelemetry traces and metrics |
| `MCP_OTEL_ENDPOINT` | OTLP exporter endpoint (default `http://localhost:4317`) |

- `solveit_data_path` controls where the init hook looks for the SOLVE-IT library and data files
- `enable_full_detail_tools` is checked at registration time in `register()`; changing it requires a server restart
- `[app.search]` flags affect both the search tool's input schema (fields are conditionally included) and runtime behaviour

---

## 7. Security and FSS Compliance

### Middleware pipeline

The pipeline runs before every tool handler:

1. Replay guard (HTTP only — rejects requests outside the timestamp window)
2. I/O limit check (request size)
3. Auth check (`none` / `apikey` / `oauth` via `MCP_AUTH_MODE`)
4. Rate limit check
5. Input sanitization
6. Input validation against JSON schema

### FSS provenance

Every tool response includes a `_provenance` block (FSS-0004 §3.1) with:

- `transaction_id` — UUID v4 per call
- `parameters_cai` / `artifact_id` — SHA-256 content-addressed identifiers (RFC 8785)
- `kb_version_id` — CAI of the active KB snapshot computed at startup
- `timestamp_utc` — ISO 8601 with sub-second precision
- `result_status` / `evidentiary_status`
- Investigation context (`investigation_id`, `analyst_identity`, `agent_identity`) when supplied via HTTP headers
- Optional `signature` — Ed25519 over signed payload fields (requires `FSS_SIGNING_KEY_PATH`)

Error responses carry FSS error codes (`FSS_TOOL_UNAVAILABLE`, `FSS_PARAM_INVALID`, etc.) and `evidentiary_status: non-evidentiary`.

SOLVE-IT tools do not modify or bypass the pipeline. All data access is read-only against the local KB.
