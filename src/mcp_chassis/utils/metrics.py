"""MCP per-request metrics for the SOLVE-IT MCP Server.

Records tool call counts, durations, error rates, middleware blocks,
request/response sizes, evidentiary status, and KB health via OpenTelemetry.
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
        self._middleware_blocks: Any = None
        self._auth_failures: Any = None
        self._replay_rejections: Any = None
        self._request_size: Any = None
        self._response_size: Any = None
        self._evidentiary_counter: Any = None
        self._search_results: Any = None
        self._kb_loaded: Any = None
        self._kb_techniques: Any = None
        self._kb_weaknesses: Any = None
        self._kb_mitigations: Any = None
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
                description="Total number of tool call errors by FSS error code",
                unit="1",
            )
            self._middleware_blocks = meter.create_counter(
                "mcp.middleware.blocks",
                description="Requests blocked by middleware, by stage",
                unit="1",
            )
            self._auth_failures = meter.create_counter(
                "mcp.auth.failures",
                description="Authentication or authorisation failures by provider",
                unit="1",
            )
            self._replay_rejections = meter.create_counter(
                "mcp.replay.rejections",
                description="Requests rejected by replay prevention",
                unit="1",
            )
            self._request_size = meter.create_histogram(
                "mcp.request.size",
                description="Incoming tool argument payload size in bytes",
                unit="By",
            )
            self._response_size = meter.create_histogram(
                "mcp.response.size",
                description="Outgoing tool result payload size in bytes",
                unit="By",
            )
            self._evidentiary_counter = meter.create_counter(
                "mcp.provenance.responses",
                description="Tool responses by evidentiary status",
                unit="1",
            )
            self._search_results = meter.create_histogram(
                "mcp.search.results_count",
                description="Number of results returned by solveit_search per call",
                unit="1",
            )
            self._kb_loaded = meter.create_observable_gauge(
                "mcp.kb.loaded",
                description="1 if KB loaded successfully, 0 if failed or degraded",
                unit="1",
            )
            self._kb_techniques = meter.create_observable_gauge(
                "mcp.kb.techniques_count",
                description="Number of techniques in the loaded KB",
                unit="1",
            )
            self._kb_weaknesses = meter.create_observable_gauge(
                "mcp.kb.weaknesses_count",
                description="Number of weaknesses in the loaded KB",
                unit="1",
            )
            self._kb_mitigations = meter.create_observable_gauge(
                "mcp.kb.mitigations_count",
                description="Number of mitigations in the loaded KB",
                unit="1",
            )
        except Exception:
            pass

    # ── Tool call lifecycle ───────────────────────────────────────────────────

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
        fss_error_code: str = "",
    ) -> None:
        """Record call completion with duration and optional FSS error code."""
        duration_ms = (time.monotonic() - start_time) * 1000
        attrs = {"tool.name": tool_name}
        if self._duration_histogram is not None:
            self._duration_histogram.record(duration_ms, attrs)
        if fss_error_code and self._error_counter is not None:
            self._error_counter.add(1, {**attrs, "fss.error_code": fss_error_code})

    # ── Request / response sizing ─────────────────────────────────────────────

    def record_request_size(self, tool_name: str, size_bytes: int) -> None:
        if self._request_size is not None:
            self._request_size.record(size_bytes, {"tool.name": tool_name})

    def record_response_size(self, tool_name: str, size_bytes: int) -> None:
        if self._response_size is not None:
            self._response_size.record(size_bytes, {"tool.name": tool_name})

    # ── Middleware ────────────────────────────────────────────────────────────

    def record_middleware_block(self, tool_name: str, stage: str) -> None:
        """Record a middleware block. stage: auth | rate_limit | validation | sanitization | replay | io_limit"""  # noqa: E501
        if self._middleware_blocks is not None:
            self._middleware_blocks.add(1, {"tool.name": tool_name, "stage": stage})

    def record_auth_failure(self, provider: str) -> None:
        if self._auth_failures is not None:
            self._auth_failures.add(1, {"auth.provider": provider})

    def record_replay_rejection(self) -> None:
        if self._replay_rejections is not None:
            self._replay_rejections.add(1)

    # ── Provenance / evidentiary ──────────────────────────────────────────────

    def record_evidentiary(self, tool_name: str, *, evidentiary: bool) -> None:
        if self._evidentiary_counter is not None:
            self._evidentiary_counter.add(
                1,
                {"tool.name": tool_name, "evidentiary": str(evidentiary).lower()},
            )

    # ── Search ────────────────────────────────────────────────────────────────

    def record_search_results(self, count: int) -> None:
        if self._search_results is not None:
            self._search_results.record(count)

    # ── KB health (called from solveit_init) ──────────────────────────────────

    def register_kb_gauges(
        self,
        *,
        loaded: bool,
        techniques: int = 0,
        weaknesses: int = 0,
        mitigations: int = 0,
    ) -> None:
        """Register observable gauge callbacks with current KB state."""
        loaded_val = 1 if loaded else 0
        t, w, m = techniques, weaknesses, mitigations

        try:
            if self._kb_loaded is not None:
                self._kb_loaded.add_callbacks(lambda o: [o.observe(loaded_val)])  # type: ignore[attr-defined]
            if self._kb_techniques is not None:
                self._kb_techniques.add_callbacks(lambda o: [o.observe(t)])  # type: ignore[attr-defined]
            if self._kb_weaknesses is not None:
                self._kb_weaknesses.add_callbacks(lambda o: [o.observe(w)])  # type: ignore[attr-defined]
            if self._kb_mitigations is not None:
                self._kb_mitigations.add_callbacks(lambda o: [o.observe(m)])  # type: ignore[attr-defined]
        except Exception:
            pass


# Module-level singleton
_metrics: MCPMetrics | None = None


def get_metrics() -> MCPMetrics:
    """Return the module-level MCPMetrics singleton."""
    global _metrics
    if _metrics is None:
        _metrics = MCPMetrics()
    return _metrics


__all__ = ["MCPMetrics", "get_metrics"]
