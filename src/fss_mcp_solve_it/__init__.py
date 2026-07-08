"""FSS MCP SOLVE-IT — MCP server for the SOLVE-IT digital forensics knowledge base."""

from importlib.metadata import PackageNotFoundError, version
try:
    __version__ = version("fss-mcp-solve-it")
except PackageNotFoundError:
    __version__ = "unknown"
