# For Researchers

This guide is for academic researchers studying digital forensics, conducting empirical studies, or citing SOLVE-IT in scholarly work.

## Citing the Software

### BibTeX

```bibtex
@software{mcp_solve_it,
  author  = {3soos3},
  title   = {SOLVE-IT MCP Server (Chassis): MCP Server for the SOLVE-IT Digital Forensics Knowledge Base},
  year    = {2026},
  url     = {https://github.com/3soos3/mcp-solve-it},
  version = {0.1.0}
}
```

### Citing the SOLVE-IT Framework

Also cite the underlying framework:

```bibtex
@misc{solveit_framework,
  author = {SOLVE-IT-DF},
  title  = {SOLVE-IT: Standardized Framework for Digital Forensics Investigation},
  year   = {2025},
  url    = {https://github.com/SOLVE-IT-DF/solve-it}
}
```

### APA

> 3soos3. (2026). *SOLVE-IT MCP Server (Chassis)* (Version 0.1.0) [Computer software]. https://github.com/3soos3/mcp-solve-it

### IEEE

> [1] 3soos3, "SOLVE-IT MCP Server (Chassis)," Version 0.1.0, 2026. [Online]. Available: https://github.com/3soos3/mcp-solve-it

## Reproducibility

### Pin the Exact Version

For reproducible research, pin a specific Git commit or tagged release rather than using `main`:

```bash
git clone https://github.com/3soos3/mcp-solve-it.git
cd mcp-solve-it
git checkout v0.1.0    # or a specific commit SHA
pip install -e .
```

Also pin the SOLVE-IT data repository:

```bash
git clone https://github.com/SOLVE-IT-DF/solve-it.git
cd solve-it
git checkout <release-tag-or-sha>
```

Document both SHAs in your research data:

```
MCP server: github.com/3soos3/mcp-solve-it @ <sha>
SOLVE-IT data: github.com/SOLVE-IT-DF/solve-it @ <sha>
```

### Data Provenance Statement

Example statement for papers:

> Data was accessed via SOLVE-IT MCP Server version 0.1.0 (github.com/3soos3/mcp-solve-it, commit SHA: [sha]) connected to SOLVE-IT framework data (github.com/SOLVE-IT-DF/solve-it, commit SHA: [sha]).

## Research Use Cases

### Bulk Data Export

Enable full-detail listing tools by setting in `config/default.toml`:

```toml
[app]
enable_full_detail_tools = true

[security.io_limits]
max_response_size = 20971520  # 20 MB
```

With these tools enabled, an LLM session or a script using the MCP protocol can export the complete dataset. The tools are:

- `solveit_list_techniques_full_detail` — all techniques with complete field data
- `solveit_list_weaknesses_full_detail` — all weaknesses with complete field data
- `solveit_list_mitigations_full_detail` — all mitigations with complete field data

!!! warning "Context window impact"
    Each full-detail tool returns 25,000–32,000 tokens of data. Use these tools only when you need the complete dataset; for most queries, the summary listing tools (`solveit_list_techniques`, etc.) and individual lookup tools are more efficient.

### Weakness–Mitigation Coverage Analysis

Start a Python session or Jupyter notebook and use the MCP protocol directly (stdio transport) or connect via your LLM client. Alternatively, write a script that uses the `mcp` Python library to call tools programmatically.

A typical analysis pattern:

1. Call `solveit_list_weaknesses` to get all weakness IDs
2. For each weakness, call `solveit_get_mitigations_for_weakness`
3. Count and analyze mitigation coverage

### Empirical Analysis of Knowledge Base Structure

Use `solveit_list_objectives` to enumerate all forensic objectives, then `solveit_get_techniques_for_objective` to retrieve the techniques under each objective. This lets you analyze the distribution of techniques across investigation phases.

### Jupyter Notebook Integration

Run the server in a subprocess or connect via your MCP client. The standard `mcp` Python library can be used to call tools from a notebook environment.

## Data Structure

The SOLVE-IT knowledge base is organized as:

```
SOLVE-IT Framework
├── Techniques (DFT-XXXX)
│   ├── ID, Name, Description, Procedure
│   ├── Weaknesses (references to DFW-XXXX)
│   └── Objectives (references)
├── Weaknesses (DFW-XXXX)
│   ├── ID, Name, Description
│   ├── Related Techniques
│   └── Mitigations (references to DFM-XXXX)
├── Mitigations (DFM-XXXX)
│   ├── ID, Name, Description
│   └── Addressed Weaknesses
└── Citations (DFCite-XXXX)
    └── Full bibliographic text (BibTeX and/or plaintext)
```

All IDs are stable across versions within a major release. Cross-version stability is documented in the SOLVE-IT repository.

## Publishing Your Research

### Data Availability Statement

> **Data Availability**: This research used SOLVE-IT MCP Server version 0.1.0 (github.com/3soos3/mcp-solve-it, commit: [sha]) with SOLVE-IT framework data (github.com/SOLVE-IT-DF/solve-it, commit: [sha]). The complete dataset is publicly available. Analysis scripts and processed data are available at [URL].

### Recommended Repository Structure

```
research-repository/
├── README.md
├── environment.txt          # Exact git SHAs of mcp-solve-it and solve-it
├── config/
│   └── default.toml         # Your server config, with solveit_data_path documented
├── data/
│   ├── raw/                 # Raw SOLVE-IT exports
│   ├── processed/           # Your processed datasets
│   └── metadata.json        # Data provenance (SHAs, timestamps)
└── scripts/
    ├── 01_collect.py
    ├── 02_analyze.py
    └── 03_visualize.py
```

## Ethical Considerations

- **Acknowledge limitations**: The framework is evolving and may not be comprehensive for all forensics sub-disciplines
- **Avoid overgeneralization**: Findings are specific to the framework version studied
- **Protect privacy**: If combining with real-world case data, apply proper anonymization
- **Follow ethics guidelines** of your institution when your research involves human subjects or case data

## Community

- [SOLVE-IT Discussions](https://github.com/SOLVE-IT-DF/solve-it/discussions)
- Digital forensics conferences: DFRWS, IFIP WG 11.9

## License

MIT License — allows commercial and academic use, modification, and distribution. Attribution required.

## Next Steps

- [Tools Overview](../reference/tools-overview.md) — all available tools
- [Getting Started](../getting-started.md) — setup and configuration
- [Troubleshooting](troubleshooting.md) — common issues
