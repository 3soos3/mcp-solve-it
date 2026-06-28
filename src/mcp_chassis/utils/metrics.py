"""MCP per-request metrics for the SOLVE-IT MCP Server.

Records tool call counts, durations, and error rates via OpenTelemetry.
Zero cost when MCP_OTEL_ENABLED is unset or false.
"""

from __future__ import annotations

import time
from typing import Any


class MCPMetrics:
    """Records per-dispatch metrics to the OTel Meter."""

    def __init__(self) -> None:
        self._call_counter: Any = None
        self._duration_histogram: Any = None
        self._error_counter: Any = None
        self._init_meters()

    def _init_meters(self) -> None:
        from mcp_chassis.utils.telemetry import get_telemetry

        tm = get_telemetry()
        if not tm.enabled or tm.get_meter() is None:
            return
        meter = tm.get_meter()
        try:
            self._call_counter = meter.create_counter(
                "mcp.tool.calls",
                description="Total number of tool calls",
                unit="1",
            )
            self._duration_histogram = meter.create_histogram(
                "mcp.tool.duration",
                description="Tool call duration in milliseconds",
                unit="ms",
            )
            self._error_counter = meter.create_counter(
                "mcp.tool.errors",
                description="Total number of tool call errors",
                unit="1",
            )
        except Exception:
            pass

    def record_call_start(self, tool_name: str) -> float:
        """Record a call start and return the start timestamp."""
        if self._call_counter is not None:
            self._call_counter.add(1, {"tool.name": tool_name})
        return time.monotonic()

    def record_call_end(
        self,
        tool_name: str,
        start_time: float,
        *,
        error_code: str = "",
    ) -> None:
        """Record call completion with duration and optional error."""
        duration_ms = (time.monotonic() - start_time) * 1000
        attrs = {"tool.name": tool_name}
        if self._duration_histogram is not None:
            self._duration_histogram.record(duration_ms, attrs)
        if error_code and self._error_counter is not None:
            self._error_counter.add(1, {**attrs, "error.code": error_code})


# Module-level singleton
_metrics: MCPMetrics | None = None


def get_metrics() -> MCPMetrics:
    """Return the module-level MCPMetrics singleton."""
    global _metrics
    if _metrics is None:
        _metrics = MCPMetrics()
    return _metrics


__all__ = ["MCPMetrics", "get_metrics"]
