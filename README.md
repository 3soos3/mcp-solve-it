# SOLVE-IT MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that exposes the [SOLVE-IT](https://github.com/SOLVE-IT-DF/solve-it) digital forensics knowledge base to LLM clients. Built on [fss-mcp](https://github.com/3soos3/fss-chassis) — every tool response carries a cryptographically-linked FSS provenance record.

SOLVE-IT provides a structured taxonomy of digital forensic techniques (DFT), the weaknesses that affect evidence reliability (DFW), and the mitigations that address those weaknesses (DFM).

---

## Quick Start

Requires [uv](https://docs.astral.sh/uv/) and a local clone of [SOLVE-IT](https://github.com/SOLVE-IT-DF/solve-it).

```bash
git clone https://github.com/3soos3/mcp-solve-it
cd mcp-solve-it
uv sync
```

Set the KB path in `config/default.toml`:

```toml
[app]
solveit_data_path = "/absolute/path/to/solve-it-main"
```

Run (stdio):

```bash
python -m fss_mcp --config config/default.toml
```

---

## MCP Client Configuration

Use absolute paths so the server works regardless of the client's working directory.

### Claude Code

Add to `.mcp.json` in your project:

```json
{
  "mcpServers": {
    "solveit": {
      "type": "stdio",
      "command": "python3",
      "args": ["-m", "fss_mcp", "--config", "/path/to/mcp-solve-it/config/default.toml"]
    }
  }
}
```

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "solveit": {
      "command": "python3",
      "args": ["-m", "fss_mcp", "--config", "/path/to/mcp-solve-it/config/default.toml"]
    }
  }
}
```

---

## Docker

Three image modes are available, controlled by the `SOLVE_IT_MODE` build argument:

| Mode | Data strategy | `FSS_METADATA` default |
|---|---|---|
| `release` | Bakes a specific SOLVE-IT release tag; deterministic, citable | `true` |
| `monthly` | Bakes SHA-pinned HEAD; reproducible within a month | `false` |
| `live` | No baked data; entrypoint fetches latest at startup and checks daily | `false` |

```bash
# Live image (no data baked in — pulls at runtime)
podman build --build-arg SOLVE_IT_MODE=live -t mcp-solve-it:live .

# Run with a local KB volume (bypasses network fetch)
podman run --rm -it \
  -e SOLVE_IT_LIVE_UPDATES=false \
  -e MCP_APP_SOLVEIT_DATA_PATH=/kb \
  -e MCP_TRANSPORT=stdio \
  -v /path/to/solve-it-main:/kb:ro \
  mcp-solve-it:live
```

Docker Compose files are provided for both standard and live-data deployments.

---

## Available Tools

### Status (always available)

| Tool | Description |
|---|---|
| `solveit_status` | KB load status, item counts, and active configuration |

### Orientation

| Tool | Description |
|---|---|
| `solveit_get_database_description` | Call first — returns DB structure, entity types, available mappings, and item counts |

### Lookup

| Tool | Description |
|---|---|
| `solveit_get_technique` | Full details for a technique by DFT-XXXX ID |
| `solveit_get_weakness` | Full details for a weakness by DFW-XXXX ID |
| `solveit_get_mitigation` | Full details for a mitigation by DFM-XXXX ID |

### Summary Listings

| Tool | Description |
|---|---|
| `solveit_list_techniques` | All techniques with ID and name |
| `solveit_list_weaknesses` | All weaknesses with ID and name |
| `solveit_list_mitigations` | All mitigations with ID and name |

### Objectives and Mappings

| Tool | Description |
|---|---|
| `solveit_list_objectives` | All forensic objectives in the active mapping |
| `solveit_get_techniques_for_objective` | Techniques under a given objective |
| `solveit_get_objectives_for_technique` | Objectives a technique belongs to (reverse) |
| `solveit_list_available_mappings` | Available framework mapping files |
| `solveit_load_objective_mapping` | Switch to a different investigation framework |

### Relationships

| Tool | Description |
|---|---|
| `solveit_get_weaknesses_for_technique` | Weaknesses that affect a technique |
| `solveit_get_mitigations_for_weakness` | Mitigations that address a weakness |
| `solveit_get_mitigations_for_technique` | Mitigations for a technique (shortcut) |
| `solveit_get_techniques_for_weakness` | Techniques affected by a weakness (reverse) |
| `solveit_get_weaknesses_for_mitigation` | Weaknesses addressed by a mitigation (reverse) |
| `solveit_get_techniques_for_mitigation` | Techniques linked to a mitigation (reverse) |

### Search

| Tool | Description |
|---|---|
| `solveit_search` | Full-text search across techniques, weaknesses, and mitigations |

### Citations

| Tool | Description |
|---|---|
| `solveit_get_citation` | Resolve a DFCite-XXXX ID to full bibliographic text |
| `solveit_list_citations` | All citation IDs in the knowledge base |
| `solveit_resolve_inline_citations` | Replace [DFCite-XXXX] markers with Harvard-style citations |

### Extension Info

| Tool | Description |
|---|---|
| `solveit_list_loaded_extensions` | SOLVE-IT-X extension datasets currently loaded |

### Full-Detail Listings (disabled by default)

These return the complete dataset for an entire item type (~25,000–32,000 tokens). Enable in `config/default.toml` and raise `max_response_size` accordingly.

| Tool | Description |
|---|---|
| `solveit_list_techniques_full_detail` | All techniques with complete field data |
| `solveit_list_weaknesses_full_detail` | All weaknesses with complete field data |
| `solveit_list_mitigations_full_detail` | All mitigations with complete field data |

---

## Configuration

### SOLVE-IT data path (required)

```toml
[app]
solveit_data_path = "/absolute/path/to/solve-it-main"
```

Can be overridden at runtime with `MCP_APP_SOLVEIT_DATA_PATH`.

### Key app settings

| Key | Default | Description |
|---|---|---|
| `objective_mapping` | `"solve-it.json"` | Mapping file inside the SOLVE-IT `data/` directory |
| `enable_extensions` | `true` | Load SOLVE-IT-X extension datasets |
| `init_required` | `true` | Exit on KB load failure (set `false` for degraded dev mode) |
| `enable_full_detail_tools` | `false` | Register the three full-detail listing tools |

Environment variable overrides use the `MCP_APP_` prefix (e.g. `MCP_APP_SOLVEIT_DATA_PATH`).

### Security profile

```toml
[security]
profile = "moderate"   # strict | moderate | permissive
```

| Profile | Rate limit | I/O limits | Sanitisation |
|---|---|---|---|
| `strict` | 60 rpm global / 30 rpm per tool | 1 MB req / 5 MB resp | Path traversal, shell metacharacters, control chars |
| `moderate` | 120 rpm global / 60 rpm per tool | 5 MB req / 20 MB resp | Path traversal, control chars |
| `permissive` | Disabled | 50 MB req/resp | Null bytes only |

---

## FSS Provenance

Every tool response includes a `_provenance` block containing:

- `transaction_id` — UUID v4 for this call
- `tool_version`, `server_version` — package versions (`fss-mcp-solve-it`)
- `kb_version_id` — SHA-256 CAI of the active SOLVE-IT snapshot
- `parameters_cai`, `result_cai` — content-addressed digests of inputs and output
- `assessed_under` — FSS conformance identifier (e.g. `FSS-0010v0.3@FSS-0009v0.3L1`)

Set `FSS_LEVEL=2` or `FSS_LEVEL=3` to claim a higher conformance level after completing a self-assessment against [FSS-0009](https://github.com/3soos3/fss-chassis). At L2+, responses are signed with Ed25519. The default is L1.

---

## Development

```bash
uv sync --extra dev
uv run pytest tests/unit/          # unit tests
uv run pytest tests/integration/   # integration tests (requires KB)
uv run ruff check src/ tests/
uv run mypy src/
```

Utility scripts in `scripts/`:

| Script | Purpose |
|---|---|
| `verify_provenance.py` | Verify a `_provenance` record from a tool response (FSS-0005 §8) |
| `validate_dataset.py` | Check KB structural integrity (FSS-0006 §4.4) |

---

## Project Structure

```
src/fss_mcp_solve_it/
  __init__.py              — package version
  solveit_init.py          — init hook: loads KB, computes KB version CAI, stamps server version
  tools/
    solveit_tools.py       — all tool registrations and handlers
config/
  default.toml             — server and application configuration
scripts/
  verify_provenance.py     — provenance record verifier
  validate_dataset.py      — KB structural integrity checker
tests/
  unit/                    — unit tests
  integration/             — integration tests (require live KB)
  stress/                  — Locust load tests
```
