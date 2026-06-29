"""Optional OpenTelemetry integration for the SOLVE-IT MCP Server.

Activated by setting MCP_OTEL_ENABLED=true. Zero cost when disabled.
Exports traces and metrics via OTLP to MCP_OTEL_ENDPOINT.

FSS relevance: OTel provides the observability infrastructure that
Profile B/C servers can use to implement tamper-evident audit trails
(FSS-0004 §5.2). Profile A servers benefit from traces for debugging.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class TelemetryManager:
    """Manages OpenTelemetry SDK initialisation and shutdown.

    Usage:
        manager = TelemetryManager()
        if manager.enabled:
            with manager.start_span("tool_call") as span:
                span.set_attribute("tool.name", "solveit_search")
    """

    def __init__(self) -> None:
        self.enabled = os.environ.get("MCP_OTEL_ENABLED", "").lower() in ("1", "true", "yes")
        self._tracer: Any = None
        self._meter: Any = None

        if self.enabled:
            self._init_otel()

    def _init_otel(self) -> None:
        endpoint = os.environ.get("MCP_OTEL_ENDPOINT", "http://localhost:4317")
        service_name = os.environ.get("MCP_OTEL_SERVICE_NAME", "mcp-solve-it")
        environment = os.environ.get("MCP_OTEL_ENVIRONMENT", "production")

        try:
            from opentelemetry import metrics, trace
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter,
            )
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            resource = Resource.create(
                {
                    "service.name": service_name,
                    "service.version": os.environ.get("SOLVE_IT_VERSION", "unknown"),
                    "deployment.environment": environment,
                }
            )

            tracer_provider = TracerProvider(resource=resource)
            tracer_provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
            )
            trace.set_tracer_provider(tracer_provider)
            self._tracer = trace.get_tracer(service_name)

            metric_reader = PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=endpoint), export_interval_millis=60_000
            )
            meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
            metrics.set_meter_provider(meter_provider)
            self._meter = metrics.get_meter(service_name)

            logger.info(
                "OpenTelemetry initialised (service=%s, endpoint=%s, env=%s)",
                service_name,
                endpoint,
                environment,
            )

        except ImportError as exc:
            logger.warning(
                "OpenTelemetry packages not installed — telemetry disabled. "
                "Run: pip install opentelemetry-api opentelemetry-sdk "
                "opentelemetry-exporter-otlp-proto-grpc (%s)",
                exc,
            )
            self.enabled = False
        except Exception as exc:
            logger.error("OpenTelemetry initialisation failed: %s", exc)
            self.enabled = False

    def start_span(self, name: str, **attributes: Any) -> Any:
        """Start a new trace span. Returns a no-op context manager if disabled."""
        if self._tracer is None:
            return _NoOpSpan()
        span = self._tracer.start_as_current_span(name)
        return span

    def get_meter(self) -> Any:
        """Return the OTel Meter, or None if telemetry is disabled."""
        return self._meter

    def shutdown(self) -> None:
        """Flush and shut down all OTel providers."""
        if not self.enabled:
            return
        try:
            from opentelemetry import metrics, trace

            tp = trace.get_tracer_provider()
            if hasattr(tp, "shutdown"):
                tp.shutdown()
            mp = metrics.get_meter_provider()
            if hasattr(mp, "shutdown"):
                mp.shutdown()
            logger.info("OpenTelemetry providers shut down")
        except Exception as exc:
            logger.warning("OTel shutdown error: %s", exc)


class _NoOpSpan:
    """No-op context manager returned when telemetry is disabled."""

    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def record_exception(self, exc: Exception) -> None:
        pass


# Module-level singleton — initialised once on first import
_manager: TelemetryManager | None = None


def get_telemetry() -> TelemetryManager:
    """Return the module-level TelemetryManager singleton."""
    global _manager
    if _manager is None:
        _manager = TelemetryManager()
    return _manager


__all__ = ["TelemetryManager", "get_telemetry"]
