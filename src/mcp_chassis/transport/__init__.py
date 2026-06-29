"""Transport abstraction layer for the MCP Chassis server."""

from mcp_chassis.transport.base import TransportBase
from mcp_chassis.transport.stdio import StdioTransport

__all__ = [
    "TransportBase",
    "StdioTransport",
    "HTTPTransport",
]


def __getattr__(name: str) -> object:
    """Lazy-load HTTPTransport to avoid hard dependency on starlette/uvicorn."""
    if name == "HTTPTransport":
        from mcp_chassis.transport.http import HTTPTransport  # noqa: PLC0415

        return HTTPTransport
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
