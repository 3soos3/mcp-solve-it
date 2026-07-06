"""Unit tests for mcp_chassis.utils.telemetry — TelemetryManager setup."""

from __future__ import annotations

import logging
import sys
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def mock_otel(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Inject mock OTel modules into sys.modules and return key mock objects."""
    mock_trace = MagicMock()
    mock_metrics = MagicMock()
    mock_resource_cls = MagicMock()
    mock_tracer_provider_cls = MagicMock()
    mock_batch_span_processor_cls = MagicMock()
    mock_otlp_span_exporter_cls = MagicMock()
    mock_meter_provider_cls = MagicMock()
    mock_periodic_reader_cls = MagicMock()
    mock_otlp_metric_exporter_cls = MagicMock()

    mock_otel_root = MagicMock()
    mock_otel_root.trace = mock_trace
    mock_otel_root.metrics = mock_metrics

    module_map = {
        "opentelemetry": mock_otel_root,
        "opentelemetry.trace": mock_trace,
        "opentelemetry.metrics": mock_metrics,
        "opentelemetry.sdk": MagicMock(),
        "opentelemetry.sdk.trace": MagicMock(TracerProvider=mock_tracer_provider_cls),
        "opentelemetry.sdk.metrics": MagicMock(MeterProvider=mock_meter_provider_cls),
        "opentelemetry.sdk.resources": MagicMock(Resource=mock_resource_cls),
        "opentelemetry.sdk.trace.export": MagicMock(
            BatchSpanProcessor=mock_batch_span_processor_cls
        ),
        "opentelemetry.sdk.metrics.export": MagicMock(
            PeriodicExportingMetricReader=mock_periodic_reader_cls
        ),
        "opentelemetry.exporter": MagicMock(),
        "opentelemetry.exporter.otlp": MagicMock(),
        "opentelemetry.exporter.otlp.proto": MagicMock(),
        "opentelemetry.exporter.otlp.proto.grpc": MagicMock(),
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": MagicMock(
            OTLPSpanExporter=mock_otlp_span_exporter_cls
        ),
        "opentelemetry.exporter.otlp.proto.grpc.metric_exporter": MagicMock(
            OTLPMetricExporter=mock_otlp_metric_exporter_cls
        ),
    }

    for name, mod in module_map.items():
        monkeypatch.setitem(sys.modules, name, mod)

    return {
        "trace": mock_trace,
        "metrics": mock_metrics,
        "Resource": mock_resource_cls,
        "TracerProvider": mock_tracer_provider_cls,
        "BatchSpanProcessor": mock_batch_span_processor_cls,
        "OTLPSpanExporter": mock_otlp_span_exporter_cls,
        "MeterProvider": mock_meter_provider_cls,
        "PeriodicExportingMetricReader": mock_periodic_reader_cls,
        "OTLPMetricExporter": mock_otlp_metric_exporter_cls,
    }


class TestTelemetryManagerDisabled:
    """TelemetryManager must be zero-cost and stable when OTel is off."""

    def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MCP_OTEL_ENABLED", raising=False)
        from mcp_chassis.utils.telemetry import TelemetryManager

        assert TelemetryManager().enabled is False

    @pytest.mark.parametrize("value", ["false", "0", "no", "", "off", "False"])
    def test_disabled_for_falsy_env_values(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", value)
        from mcp_chassis.utils.telemetry import TelemetryManager

        assert TelemetryManager().enabled is False

    def test_tracer_and_meter_are_none_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MCP_OTEL_ENABLED", raising=False)
        from mcp_chassis.utils.telemetry import TelemetryManager

        m = TelemetryManager()
        assert m._tracer is None
        assert m._meter is None

    def test_start_span_returns_noop_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MCP_OTEL_ENABLED", raising=False)
        from mcp_chassis.utils.telemetry import TelemetryManager, _NoOpSpan

        with TelemetryManager().start_span("op") as span:
            assert isinstance(span, _NoOpSpan)

    def test_get_meter_returns_none_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MCP_OTEL_ENABLED", raising=False)
        from mcp_chassis.utils.telemetry import TelemetryManager

        assert TelemetryManager().get_meter() is None

    def test_shutdown_is_noop_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MCP_OTEL_ENABLED", raising=False)
        from mcp_chassis.utils.telemetry import TelemetryManager

        TelemetryManager().shutdown()  # must not raise


class TestTelemetryManagerEnabled:
    """TelemetryManager with OTel mocked — init, span, meter, shutdown."""

    @pytest.mark.parametrize("value", ["true", "1", "yes", "TRUE", "Yes"])
    def test_enabled_for_truthy_env_values(
        self, monkeypatch: pytest.MonkeyPatch, mock_otel: dict, value: str
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", value)
        from mcp_chassis.utils.telemetry import TelemetryManager

        assert TelemetryManager().enabled is True

    def test_tracer_and_meter_set_after_init(
        self, monkeypatch: pytest.MonkeyPatch, mock_otel: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        from mcp_chassis.utils.telemetry import TelemetryManager

        m = TelemetryManager()
        assert m._tracer is not None
        assert m._meter is not None

    def test_get_meter_returns_meter_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch, mock_otel: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        from mcp_chassis.utils.telemetry import TelemetryManager

        m = TelemetryManager()
        assert m.get_meter() is mock_otel["metrics"].get_meter.return_value

    def test_resource_built_with_default_attrs(
        self, monkeypatch: pytest.MonkeyPatch, mock_otel: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        for key in (
            "MCP_OTEL_SERVICE_NAME",
            "MCP_OTEL_ENVIRONMENT",
            "SOLVE_IT_VERSION",
            "SOLVE_IT_MODE",
            "FORENSIC_METADATA",
        ):
            monkeypatch.delenv(key, raising=False)
        import mcp_chassis
        from mcp_chassis.utils.telemetry import TelemetryManager

        TelemetryManager()
        attrs = mock_otel["Resource"].create.call_args[0][0]
        assert attrs["service.name"] == "mcp-solve-it"
        assert attrs["deployment.environment"] == "production"
        assert attrs["service.version"] == mcp_chassis.__version__

    def test_resource_built_with_env_vars(
        self, monkeypatch: pytest.MonkeyPatch, mock_otel: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        monkeypatch.setenv("MCP_OTEL_SERVICE_NAME", "my-svc")
        monkeypatch.setenv("MCP_OTEL_ENVIRONMENT", "staging")
        monkeypatch.setenv("SOLVE_IT_VERSION", "1.2.3")
        monkeypatch.setenv("SOLVE_IT_MODE", "bundle")
        monkeypatch.setenv("FORENSIC_METADATA", "true")
        import mcp_chassis
        from mcp_chassis.utils.telemetry import TelemetryManager

        TelemetryManager()
        attrs = mock_otel["Resource"].create.call_args[0][0]
        assert attrs["service.name"] == "my-svc"
        assert attrs["deployment.environment"] == "staging"
        assert attrs["service.version"] == mcp_chassis.__version__
        assert attrs["solve_it.mode"] == "bundle"
        assert attrs["solve_it.version"] == "1.2.3"
        assert attrs["forensic_metadata"] == "true"

    def test_otlp_exporters_use_default_endpoint(
        self, monkeypatch: pytest.MonkeyPatch, mock_otel: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        monkeypatch.delenv("MCP_OTEL_ENDPOINT", raising=False)
        from mcp_chassis.utils.telemetry import TelemetryManager

        TelemetryManager()
        mock_otel["OTLPSpanExporter"].assert_called_once_with(endpoint="http://localhost:4317")
        mock_otel["OTLPMetricExporter"].assert_called_once_with(endpoint="http://localhost:4317")

    def test_otlp_exporters_use_custom_endpoint(
        self, monkeypatch: pytest.MonkeyPatch, mock_otel: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        monkeypatch.setenv("MCP_OTEL_ENDPOINT", "http://otel-collector:4317")
        from mcp_chassis.utils.telemetry import TelemetryManager

        TelemetryManager()
        mock_otel["OTLPSpanExporter"].assert_called_once_with(endpoint="http://otel-collector:4317")
        mock_otel["OTLPMetricExporter"].assert_called_once_with(
            endpoint="http://otel-collector:4317"
        )

    def test_start_span_delegates_to_tracer(
        self, monkeypatch: pytest.MonkeyPatch, mock_otel: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        from mcp_chassis.utils.telemetry import TelemetryManager

        m = TelemetryManager()
        m.start_span("my_op")
        mock_otel["trace"].get_tracer.return_value.start_as_current_span.assert_called_once_with(
            "my_op"
        )

    def test_import_error_disables_telemetry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        # Setting a sys.modules entry to None causes ImportError on 'from opentelemetry import ...'
        monkeypatch.setitem(sys.modules, "opentelemetry", None)
        from mcp_chassis.utils.telemetry import TelemetryManager

        m = TelemetryManager()
        assert m.enabled is False
        assert m._tracer is None
        assert m._meter is None

    def test_init_exception_disables_telemetry(
        self, monkeypatch: pytest.MonkeyPatch, mock_otel: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        mock_otel["TracerProvider"].side_effect = RuntimeError("init boom")
        from mcp_chassis.utils.telemetry import TelemetryManager

        m = TelemetryManager()
        assert m.enabled is False

    def test_shutdown_calls_provider_shutdown(
        self, monkeypatch: pytest.MonkeyPatch, mock_otel: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        from mcp_chassis.utils.telemetry import TelemetryManager

        TelemetryManager().shutdown()
        mock_otel["trace"].get_tracer_provider.return_value.shutdown.assert_called_once()
        mock_otel["metrics"].get_meter_provider.return_value.shutdown.assert_called_once()

    def test_shutdown_handles_exception_gracefully(
        self, monkeypatch: pytest.MonkeyPatch, mock_otel: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        mock_otel["trace"].get_tracer_provider.return_value.shutdown.side_effect = RuntimeError(
            "shutdown boom"
        )
        from mcp_chassis.utils.telemetry import TelemetryManager

        TelemetryManager().shutdown()  # must not raise

    def test_init_logs_info_on_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_otel: dict,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        from mcp_chassis.utils.telemetry import TelemetryManager

        with caplog.at_level(logging.INFO, logger="mcp_chassis.utils.telemetry"):
            TelemetryManager()
        assert "OpenTelemetry initialised" in caplog.text

    def test_import_error_logs_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        monkeypatch.setitem(sys.modules, "opentelemetry", None)
        from mcp_chassis.utils.telemetry import TelemetryManager

        with caplog.at_level(logging.WARNING, logger="mcp_chassis.utils.telemetry"):
            TelemetryManager()
        assert "not installed" in caplog.text

    def test_init_exception_logs_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_otel: dict,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        mock_otel["TracerProvider"].side_effect = RuntimeError("boom")
        from mcp_chassis.utils.telemetry import TelemetryManager

        with caplog.at_level(logging.ERROR, logger="mcp_chassis.utils.telemetry"):
            TelemetryManager()
        assert "initialisation failed" in caplog.text


class TestNoOpSpan:
    """_NoOpSpan is a valid no-op context manager."""

    def test_context_manager_protocol(self) -> None:
        from mcp_chassis.utils.telemetry import _NoOpSpan

        with _NoOpSpan() as span:
            assert isinstance(span, _NoOpSpan)

    def test_set_attribute_is_noop(self) -> None:
        from mcp_chassis.utils.telemetry import _NoOpSpan

        _NoOpSpan().set_attribute("key", "value")

    def test_record_exception_is_noop(self) -> None:
        from mcp_chassis.utils.telemetry import _NoOpSpan

        _NoOpSpan().record_exception(ValueError("boom"))


class TestGetTelemetrySingleton:
    """get_telemetry() returns a stable module-level singleton."""

    def test_returns_same_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("mcp_chassis.utils.telemetry._manager", None)
        monkeypatch.delenv("MCP_OTEL_ENABLED", raising=False)
        from mcp_chassis.utils.telemetry import get_telemetry

        assert get_telemetry() is get_telemetry()

    def test_creates_telemetry_manager_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("mcp_chassis.utils.telemetry._manager", None)
        monkeypatch.delenv("MCP_OTEL_ENABLED", raising=False)
        from mcp_chassis.utils.telemetry import TelemetryManager, get_telemetry

        assert isinstance(get_telemetry(), TelemetryManager)


# ── Real-SDK tests ────────────────────────────────────────────────────────────
#
# These tests wire the real OpenTelemetry SDK against in-memory exporters
# (no OTLP network calls).  They verify what the mock tests cannot: that our
# resource attributes actually reach the SDK, that start_span produces a real
# exported span, and that get_meter returns a working meter.


@pytest.fixture()
def real_sdk_setup(monkeypatch: pytest.MonkeyPatch) -> Generator[dict, None, None]:
    """Run _init_otel with real OTel SDK but swap OTLP exporters for in-memory ones.

    Captures the TracerProvider / MeterProvider without registering them as
    global OTel singletons, so tests are fully isolated from each other and
    from the module-level _manager singleton.
    """
    import opentelemetry.exporter.otlp.proto.grpc.metric_exporter as me_mod
    import opentelemetry.exporter.otlp.proto.grpc.trace_exporter as te_mod
    import opentelemetry.metrics as metrics_module
    import opentelemetry.sdk.metrics.export as sme_mod
    import opentelemetry.sdk.trace.export as ste_mod
    import opentelemetry.trace as trace_module
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    span_exporter = InMemorySpanExporter()
    metric_reader = InMemoryMetricReader()
    captured: dict = {}

    # Redirect OTLP trace exporter → in-memory; BatchSpanProcessor → Simple
    # (SimpleSpanProcessor exports spans immediately rather than batching them)
    monkeypatch.setattr(te_mod, "OTLPSpanExporter", lambda **kw: span_exporter)
    monkeypatch.setattr(ste_mod, "BatchSpanProcessor", SimpleSpanProcessor)

    # Redirect OTLP metric exporter → ignored; swap reader for InMemoryMetricReader
    monkeypatch.setattr(me_mod, "OTLPMetricExporter", lambda **kw: None)
    monkeypatch.setattr(sme_mod, "PeriodicExportingMetricReader", lambda *a, **kw: metric_reader)

    # Intercept set_tracer_provider / set_meter_provider to avoid touching the
    # process-wide OTel globals, then redirect get_tracer / get_meter to the
    # captured providers so TelemetryManager._tracer / ._meter are real objects.
    monkeypatch.setattr(
        trace_module, "set_tracer_provider", lambda tp: captured.update({"tracer_provider": tp})
    )
    monkeypatch.setattr(
        metrics_module, "set_meter_provider", lambda mp: captured.update({"meter_provider": mp})
    )
    monkeypatch.setattr(
        trace_module, "get_tracer", lambda name, **kw: captured["tracer_provider"].get_tracer(name)
    )
    monkeypatch.setattr(
        metrics_module, "get_meter", lambda name, **kw: captured["meter_provider"].get_meter(name)
    )

    yield {"span_exporter": span_exporter, "metric_reader": metric_reader, "captured": captured}

    for key in ("tracer_provider", "meter_provider"):
        p = captured.get(key)
        if p and hasattr(p, "shutdown"):
            try:
                p.shutdown()
            except Exception:
                pass


class TestTelemetryManagerRealSDK:
    """TelemetryManager verified against the real OTel SDK (no mocking of SDK internals)."""

    def test_resource_has_default_service_name(
        self, monkeypatch: pytest.MonkeyPatch, real_sdk_setup: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        monkeypatch.delenv("MCP_OTEL_SERVICE_NAME", raising=False)
        from mcp_chassis.utils.telemetry import TelemetryManager

        TelemetryManager()
        attrs = dict(real_sdk_setup["captured"]["tracer_provider"].resource.attributes)
        assert attrs["service.name"] == "mcp-solve-it"

    def test_resource_has_custom_service_name(
        self, monkeypatch: pytest.MonkeyPatch, real_sdk_setup: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        monkeypatch.setenv("MCP_OTEL_SERVICE_NAME", "my-custom-svc")
        from mcp_chassis.utils.telemetry import TelemetryManager

        TelemetryManager()
        attrs = dict(real_sdk_setup["captured"]["tracer_provider"].resource.attributes)
        assert attrs["service.name"] == "my-custom-svc"

    def test_resource_deployment_environment(
        self, monkeypatch: pytest.MonkeyPatch, real_sdk_setup: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        monkeypatch.setenv("MCP_OTEL_ENVIRONMENT", "staging")
        from mcp_chassis.utils.telemetry import TelemetryManager

        TelemetryManager()
        attrs = dict(real_sdk_setup["captured"]["tracer_provider"].resource.attributes)
        assert attrs["deployment.environment"] == "staging"

    def test_resource_solve_it_attributes(
        self, monkeypatch: pytest.MonkeyPatch, real_sdk_setup: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        monkeypatch.setenv("SOLVE_IT_VERSION", "1.2.3")
        monkeypatch.setenv("SOLVE_IT_MODE", "bundle")
        monkeypatch.setenv("FORENSIC_METADATA", "true")
        import mcp_chassis
        from mcp_chassis.utils.telemetry import TelemetryManager

        TelemetryManager()
        attrs = dict(real_sdk_setup["captured"]["tracer_provider"].resource.attributes)
        assert attrs["service.version"] == mcp_chassis.__version__
        assert attrs["solve_it.mode"] == "bundle"
        assert attrs["solve_it.version"] == "1.2.3"
        assert attrs["forensic_metadata"] == "true"

    def test_start_span_produces_exportable_span(
        self, monkeypatch: pytest.MonkeyPatch, real_sdk_setup: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        from mcp_chassis.utils.telemetry import TelemetryManager

        m = TelemetryManager()
        with m.start_span("mcp.tool.call"):
            pass

        spans = real_sdk_setup["span_exporter"].get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "mcp.tool.call"

    def test_span_carries_resource_attributes(
        self, monkeypatch: pytest.MonkeyPatch, real_sdk_setup: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        monkeypatch.setenv("MCP_OTEL_SERVICE_NAME", "svc-under-test")
        monkeypatch.setenv("MCP_OTEL_ENVIRONMENT", "ci")
        from mcp_chassis.utils.telemetry import TelemetryManager

        m = TelemetryManager()
        with m.start_span("tool_call"):
            pass

        span = real_sdk_setup["span_exporter"].get_finished_spans()[0]
        res = dict(span.resource.attributes)
        assert res["service.name"] == "svc-under-test"
        assert res["deployment.environment"] == "ci"

    def test_meter_creates_usable_counter(
        self, monkeypatch: pytest.MonkeyPatch, real_sdk_setup: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        from mcp_chassis.utils.telemetry import TelemetryManager

        m = TelemetryManager()
        meter = m.get_meter()
        assert meter is not None

        counter = meter.create_counter("mcp.calls", unit="1")
        counter.add(5, {"tool.name": "solveit_status"})

        data = real_sdk_setup["metric_reader"].get_metrics_data()
        rm = data.resource_metrics
        assert len(rm) == 1
        metric = rm[0].scope_metrics[0].metrics[0]
        assert metric.name == "mcp.calls"
        dp = metric.data.data_points[0]
        assert dp.value == 5
        assert dp.attributes["tool.name"] == "solveit_status"

    def test_meter_counter_accumulates(
        self, monkeypatch: pytest.MonkeyPatch, real_sdk_setup: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        from mcp_chassis.utils.telemetry import TelemetryManager

        m = TelemetryManager()
        counter = m.get_meter().create_counter("mcp.calls", unit="1")
        counter.add(1, {"tool.name": "solveit_search"})
        counter.add(2, {"tool.name": "solveit_search"})

        data = real_sdk_setup["metric_reader"].get_metrics_data()
        dp = data.resource_metrics[0].scope_metrics[0].metrics[0].data.data_points[0]
        assert dp.value == 3

    def test_tracer_and_meter_share_same_resource(
        self, monkeypatch: pytest.MonkeyPatch, real_sdk_setup: dict
    ) -> None:
        monkeypatch.setenv("MCP_OTEL_ENABLED", "true")
        monkeypatch.setenv("MCP_OTEL_SERVICE_NAME", "shared-svc")
        from mcp_chassis.utils.telemetry import TelemetryManager

        TelemetryManager()
        captured = real_sdk_setup["captured"]
        tp_name = captured["tracer_provider"].resource.attributes["service.name"]
        # MeterProvider exposes resource via internal _sdk_config
        mp_name = captured["meter_provider"]._sdk_config.resource.attributes["service.name"]
        assert tp_name == mp_name == "shared-svc"
