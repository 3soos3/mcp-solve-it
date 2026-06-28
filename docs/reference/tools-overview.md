# Tools Overview

Complete reference for all MCP tools provided by the SOLVE-IT MCP Server.

## ID Conventions

| Prefix | Entity | Example |
|---|---|---|
| `DFT-XXXX` | Technique | `DFT-1001` |
| `DFW-XXXX` | Weakness | `DFW-1001` |
| `DFM-XXXX` | Mitigation | `DFM-1001` |
| `DFCite-XXXX` | Citation | `DFCite-1001` |

IDs are case-sensitive. Always use uppercase with a 4-digit number.

## Tool Count Summary

| Category | Count | Notes |
|---|---|---|
| Status | 1 | Always registered, even when KB fails |
| Detail (single item) | 3 | Lookup by ID |
| Bulk listing (summary) | 6 | ID and name only |
| Relationships | 5 | Traversal between item types |
| Objectives / Mappings | 2 | Objective listing and lookup |
| Citations | 2 | Citation lookup and listing |
| Search | 1 | Full-text search |
| Extension info | 1 | SOLVE-IT-X extension metadata |
| **Total (always registered)** | **21** | Available when KB loads successfully |
| Full-detail listing | 3 | Config-gated; disabled by default |
| **Grand total (with full-detail)** | **24** | When `enable_full_detail_tools = true` |

Note: `__health_check` is also registered by the chassis diagnostics subsystem, bringing the observable tool count to 22 (or 25 with full-detail tools).

---

## Status

### `solveit_status`

Returns the current health of the SOLVE-IT knowledge base, including item counts and loaded extensions.

**Parameters**: none

**Always registered** — available even when the KB failed to load. In that case, returns `{"status": "error", "error": "<message>"}`.

**Example response (healthy):**
```json
{
  "status": "ok",
  "techniques": 120,
  "weaknesses": 85,
  "mitigations": 60,
  "citations": 200
}
```

**Call this first** to confirm the server is ready before using other tools.

---

## Detail (Single Item Lookup)

These tools retrieve full details for a single item by its ID.

### `solveit_get_technique`

Get full details of a SOLVE-IT technique by its ID.

**Parameters**: `technique_id` (string, e.g. `"DFT-1001"`)

Returns the complete technique record including description, procedure, associated weaknesses, objectives, and citations.

Returns `{"error": "not_found", "id": "..."}` if the ID does not exist.

---

### `solveit_get_weakness`

Get full details of a SOLVE-IT weakness by its ID.

**Parameters**: `weakness_id` (string, e.g. `"DFW-1001"`)

Returns the complete weakness record including description, related techniques, and mitigations.

Returns `{"error": "not_found", "id": "..."}` if the ID does not exist.

---

### `solveit_get_mitigation`

Get full details of a SOLVE-IT mitigation by its ID.

**Parameters**: `mitigation_id` (string, e.g. `"DFM-1001"`)

Returns the complete mitigation record including description and addressed weaknesses.

Returns `{"error": "not_found", "id": "..."}` if the ID does not exist.

---

## Bulk Listing (Summary)

These tools list all items of a given type, returning ID and name only. Use these to discover IDs before calling detail tools.

### `solveit_list_techniques`

List all SOLVE-IT techniques (ID and name only).

**Parameters**: none

---

### `solveit_list_weaknesses`

List all SOLVE-IT weaknesses (ID and name only).

**Parameters**: none

---

### `solveit_list_mitigations`

List all SOLVE-IT mitigations (ID and name only).

**Parameters**: none

---

## Relationships

These tools traverse the connections between techniques, weaknesses, and mitigations. All relationship tools validate the provided ID before querying and return `{"error": "not_found", "id": "..."}` for unknown IDs.

### `solveit_get_weaknesses_for_technique`

Get all weaknesses associated with a given technique.

**Parameters**: `technique_id` (string, e.g. `"DFT-1001"`)

---

### `solveit_get_mitigations_for_weakness`

Get all mitigations that address a given weakness.

**Parameters**: `weakness_id` (string, e.g. `"DFW-1001"`)

---

### `solveit_get_techniques_for_weakness`

Get all techniques that can exhibit a given weakness.

**Parameters**: `weakness_id` (string, e.g. `"DFW-1001"`)

---

### `solveit_get_weaknesses_for_mitigation`

Get all weaknesses that a given mitigation addresses.

**Parameters**: `mitigation_id` (string, e.g. `"DFM-1001"`)

---

### `solveit_get_techniques_for_mitigation`

Get all techniques reachable from a given mitigation (via its addressed weaknesses).

**Parameters**: `mitigation_id` (string, e.g. `"DFM-1001"`)

---

## Objectives / Mappings

### `solveit_list_objectives`

List all objectives in the current SOLVE-IT mapping (as configured by `objective_mapping` in `config/default.toml`).

**Parameters**: none

Objectives group techniques into investigation workflow phases (e.g. "Acquire data", "Analyse data").

---

### `solveit_get_techniques_for_objective`

Get all techniques associated with a given objective name.

**Parameters**: `objective_name` (string, e.g. `"Acquire data"`)

Use `solveit_list_objectives` first to discover available objective names.

---

## Citations

### `solveit_get_citation`

Get a SOLVE-IT citation by its DFCite ID. Returns BibTeX and/or plaintext content.

**Parameters**: `citation_id` (string, e.g. `"DFCite-1001"`)

Returns `{"error": "not_found", "id": "..."}` if the ID does not exist.

---

### `solveit_list_citations`

List all citation IDs in the SOLVE-IT knowledge base.

**Parameters**: none

Returns a list of objects: `[{"id": "DFCite-1001"}, ...]`

---

## Search

### `solveit_search`

Search the SOLVE-IT knowledge base by keywords. Returns matching techniques, weaknesses, and mitigations sorted by relevance.

**Parameters**:

| Parameter | Type | Required | Description |
|---|---|---|---|
| `keywords` | string | yes | Search terms. Use quotes for exact phrases. |
| `item_types` | array of strings | no | Limit to `"techniques"`, `"weaknesses"`, `"mitigations"`. Default: all types. |
| `substring_match` | boolean | no | Allow partial word matches. Default: `false` (word-boundary matching). |
| `search_logic` | `"AND"` or `"OR"` | no | How to combine multiple keywords. Default: `"AND"`. |

The `item_types`, `substring_match`, and `search_logic` parameters are only included in the tool schema if the corresponding flags in `[app.search]` are `true`. When a flag is `false`, the parameter is hidden and its default value is applied silently.

**Example**:
```json
{
  "keywords": "memory acquisition",
  "item_types": ["techniques"],
  "search_logic": "AND"
}
```

---

## Extension Info

### `solveit_list_loaded_extensions`

List all loaded SOLVE-IT-X extensions and their details.

**Parameters**: none

Returns an empty list if `enable_extensions = false` or no extensions were found.

---

## Full-Detail Listing Tools (Config-Gated)

These three tools are **disabled by default** because they return the complete dataset for an item type in a single response, which may consume 25,000–32,000 tokens of LLM context per call.

Enable them by setting in `config/default.toml`:

```toml
[app]
enable_full_detail_tools = true

[security.io_limits]
max_response_size = 20971520   # 20 MB; the default 10 MB may be too small
```

### `solveit_list_techniques_full_detail`

List ALL techniques with complete field data.

**Parameters**: none

### `solveit_list_weaknesses_full_detail`

List ALL weaknesses with complete field data.

**Parameters**: none

### `solveit_list_mitigations_full_detail`

List ALL mitigations with complete field data.

**Parameters**: none

---

## Recommended Workflow

```
1. solveit_status                          — verify the server is healthy
2. solveit_list_objectives                 — understand the knowledge base structure
3. solveit_search (keywords)               — find relevant items by keyword
4. solveit_get_technique / _weakness / _mitigation   — get full details
5. Relationship tools                      — traverse connections
6. solveit_get_citation                    — retrieve citation details
```

## Related Documentation

- [For Forensic Analysts](../guides/for-forensic-analysts.md) — investigation workflows
- [For Researchers](../guides/for-researchers.md) — bulk export and data analysis
- [Getting Started](../getting-started.md) — configuration and setup
