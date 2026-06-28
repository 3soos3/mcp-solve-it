# SOLVE-IT MCP Server

**MCP server providing LLM access to the SOLVE-IT Digital Forensics Knowledge Base, built on the MCP Chassis framework.**

This server exposes the SOLVE-IT knowledge base through specialized MCP tools, enabling LLMs to assist with digital forensics investigations by providing structured access to:

- **Techniques** (DFT-XXXX) — digital forensic investigation methods
- **Weaknesses** (DFW-XXXX) — potential problems or limitations of techniques
- **Mitigations** (DFM-XXXX) — ways to address weaknesses
- **Citations** (DFCite-XXXX) — academic and industry references
- **Objectives** — investigation workflow phases that group techniques

The server is built on the [MCP Server Chassis](https://github.com/CKE-Proto/mcp_server-chassis/), which provides configuration management (TOML-based), a security middleware pipeline, and extension auto-discovery. SOLVE-IT-specific logic lives in a single init hook and tool extension module.

## Quick Navigation

### Getting Started

- [Getting Started](getting-started.md) — installation, configuration, and running the server
- [For Forensic Analysts](guides/for-forensic-analysts.md) — practical guide for digital forensics professionals
- [For Researchers](guides/for-researchers.md) — academic usage and citation guidance
- [Troubleshooting](guides/troubleshooting.md) — common issues and solutions

### Reference

- [Tools Overview](reference/tools-overview.md) — all 25 always-available tools plus 3 config-gated full-detail tools
- [Environment Variables](reference/environment-variables.md) — all `MCP_*` and `SOLVE_IT_*` variables

### Architecture & Deployment

- [Architecture Overview](architecture/overview.md) — chassis design, startup sequence, and request flow
- [Docker Deployment](deployment/docker.md) — building and running with Docker
- [Kubernetes Deployment](deployment/kubernetes.md) — production Kubernetes setup

## Key Features

- **TOML Configuration**: All settings in `config/default.toml` with optional `MCP_APP_*` environment variable overrides
- **Chassis Security Middleware**: Every tool request passes through I/O limits, auth, rate limiting, sanitization, and validation
- **Extension Auto-Discovery**: Tools are auto-discovered from `extensions/tools/` at startup
- **Stdio by Default**: Designed for desktop MCP clients; HTTP transport available via config
- **Degraded-Mode Support**: Server can start with only `solveit_status` available when KB fails to load (`init_required = false`)
- **Config-Gated Full-Detail Tools**: Three large-payload listing tools disabled by default to protect context window

## About SOLVE-IT

SOLVE-IT is a systematic digital forensics knowledge base inspired by MITRE ATT&CK. It provides structured mappings of investigation techniques, their weaknesses, and mitigations.

**Learn more**: [SOLVE-IT-DF/solve-it on GitHub](https://github.com/SOLVE-IT-DF/solve-it)

## Related Repositories

- **SOLVE-IT**: [SOLVE-IT-DF/solve-it](https://github.com/SOLVE-IT-DF/solve-it) — the knowledge base this server wraps
- **MCP Server Chassis**: [CKE-Proto/mcp_server-chassis](https://github.com/CKE-Proto/mcp_server-chassis/) — the framework this server is built on

## License

This project is licensed under the MIT License.
