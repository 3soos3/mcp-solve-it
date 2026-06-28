# For Forensic Analysts

This guide is for digital forensics professionals using the SOLVE-IT MCP Server in casework and investigations.

## Overview

The SOLVE-IT MCP Server gives an LLM programmatic access to a structured knowledge base of forensic techniques, their known weaknesses, and recommended mitigations. When connected to Claude or another MCP-capable LLM, it supports:

- **Technique selection**: Find the right method for a given evidence type or scenario
- **Methodology validation**: Identify and document the limitations of your chosen techniques
- **Report documentation**: Reference techniques, weaknesses, and mitigations by stable ID (DFT-XXXX, DFW-XXXX, DFM-XXXX)
- **Defensibility**: Demonstrate systematic, documented decision-making

## Setup

Follow the [Getting Started](../getting-started.md) guide to install and configure the server, then connect it to your MCP client of choice.

Once connected, the LLM can call SOLVE-IT tools on your behalf. You interact in natural language; the LLM handles tool invocation.

## Recommended Tool Workflow

The standard investigation workflow uses tools in this order:

1. **`solveit_status`** — Confirm the server is healthy and check item counts
2. **`solveit_search`** — Find relevant techniques, weaknesses, or mitigations by keyword
3. **`solveit_get_technique` / `solveit_get_weakness` / `solveit_get_mitigation`** — Get full details for specific items
4. **Relationship tools** — Traverse connections between items

### Step 1: Check Status

Always start by confirming the KB is loaded:

Ask your LLM: *"Check the SOLVE-IT status."*

The `solveit_status` tool returns item counts and loaded extensions. If it reports an error, the server is running in degraded mode and the KB has not loaded — see [Troubleshooting](troubleshooting.md).

### Step 2: Get the Database Description

For a first session, ask the LLM to describe the knowledge base structure:

Ask your LLM: *"Describe the SOLVE-IT knowledge base — what types of items does it contain and how are they organized?"*

The LLM will use `solveit_list_objectives`, `solveit_list_techniques`, and `solveit_status` to construct a useful overview.

### Step 3: Search

Ask your LLM: *"Search for techniques related to mobile device acquisition."*

The LLM calls `solveit_search` with appropriate keywords. Results are returned sorted by relevance.

Useful search options the LLM can use:

- `item_types`: limit to `["techniques"]`, `["weaknesses"]`, or `["mitigations"]`
- `search_logic`: `"AND"` (all keywords must match, default) or `"OR"` (any keyword matches)
- `substring_match`: `true` for partial word matching

### Step 4: Get Details

Once you have an ID, ask for full details:

Ask your LLM: *"Get the full details of DFT-1001."*

The LLM calls `solveit_get_technique`. The response includes the technique's description, procedure, weaknesses, and citations.

### Step 5: Traverse Relationships

Explore the connections between items:

- *"What weaknesses affect DFT-1001?"* → `solveit_get_weaknesses_for_technique`
- *"What mitigations address DFW-1015?"* → `solveit_get_mitigations_for_weakness`
- *"What techniques can exhibit DFW-1015?"* → `solveit_get_techniques_for_weakness`
- *"What weaknesses does DFM-1004 address?"* → `solveit_get_weaknesses_for_mitigation`

## Investigation Workflows

### Workflow 1: Finding the Right Technique

**Scenario**: You have seized a network router and need to determine the best approach for evidence extraction.

1. Ask: *"Search for techniques related to network device forensics."*
2. Review search results. Ask for full details on promising candidates: *"Get details on DFT-1042."*
3. Ask: *"What weaknesses affect this technique?"*
4. Ask: *"What mitigations address those weaknesses?"*
5. Document the technique ID and the mitigations you will apply.

### Workflow 2: Investigation Planning by Objective

**Scenario**: Planning a mobile device investigation and ensuring comprehensive coverage.

1. Ask: *"List all SOLVE-IT forensic objectives."* — calls `solveit_list_objectives`
2. Ask: *"What techniques are available under the mobile device acquisition objective?"* — calls `solveit_get_techniques_for_objective`
3. For each relevant technique, follow Workflow 1 to understand weaknesses and mitigations.

### Workflow 3: Methodology Documentation

**Scenario**: Preparing expert testimony and needing to document strengths and limitations of your approach.

1. List all techniques used in the investigation.
2. For each, ask the LLM to retrieve weaknesses and the mitigations you applied.
3. Ask the LLM to draft a methodology section using the structured information.

**Example methodology section for a report:**

```markdown
## Investigation Methodology

### Network Traffic Analysis (DFT-1023)

**Purpose**: Identify suspicious network communications.

**Weaknesses considered**:
- DFW-1008: Encrypted traffic may not be fully analyzable
- DFW-1012: Incomplete packet capture due to tap limitations

**Mitigations applied**:
- DFM-1004: Captured full packet headers and metadata
- DFM-1009: Cross-referenced with firewall logs for context
- DFM-1015: Documented capture timestamps and chain of custody

**Justification**: Despite acknowledged limitations, this technique provided
crucial evidence of C2 communication patterns corroborating endpoint findings.
```

## Working with Citations

SOLVE-IT techniques and weaknesses reference citations in the form `DFCite-XXXX`. To retrieve a citation:

Ask: *"Get the citation DFCite-1001."* — calls `solveit_get_citation`

To list all available citations: *"List all SOLVE-IT citations."* — calls `solveit_list_citations`

## SOLVE-IT-X Extensions

If `enable_extensions = true` in `config/default.toml`, the server loads any SOLVE-IT-X extension datasets present in the repository. To check which extensions are loaded:

Ask: *"List loaded SOLVE-IT extensions."* — calls `solveit_list_loaded_extensions`

The `solveit_status` tool also reports loaded extensions.

## Best Practices

**Documentation**

- Reference technique IDs in reports (e.g. "Network Traffic Analysis (DFT-1023)")
- Document weaknesses you identified and considered, including those you decided were not material
- Justify mitigation choices explicitly
- Use consistent IDs across all documentation for a case

**Defensibility**

- Show awareness of limitations before being challenged on them
- Document alternatives considered and why you chose otherwise
- Demonstrate a systematic, reproducible approach

**Court Reference**

SOLVE-IT is a published, peer-reviewed framework. A standard reference is:

> "SOLVE-IT Digital Forensics Framework (SOLVE-IT-DF/solve-it, https://github.com/SOLVE-IT-DF/solve-it)"

Always consult your legal team regarding expert testimony requirements in your jurisdiction.

## Troubleshooting

If searches return no results or tools return errors, see [Troubleshooting](troubleshooting.md).

Common issues:

- **Missing tools**: The KB did not load — check `solveit_status` and review startup logs
- **Empty search results**: Try `search_logic = "OR"` or `substring_match = true`
- **`not_found` for a valid ID**: Check case sensitivity (IDs are uppercase, e.g. `DFT-1001` not `dft-1001`)

## Next Steps

- [Tools Overview](../reference/tools-overview.md) — complete list of all tools
- [Integration Guide](integration.md) — connecting to different MCP clients
- [Troubleshooting](troubleshooting.md) — common issues and fixes
