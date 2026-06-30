"""Unit tests for mcp_chassis.utils.metrics — OTel per-dispatch recording (L3-11)."""

from __future__ import annotations

import time

import pytest


class TestMCPMetricsWithoutOTel:
    """MCPMetrics must be zero-cost and non-crashing when OTel is disabled."""

    def test_get_metrics_returns_instance(self) -> None:
        from mcp_chassis.utils.metrics import MCPMetrics, get_metrics

        m = get_metrics()
        assert isinstance(m, MCPMetrics)

    def test_get_metrics_is_singleton(self) -> None:
        from mcp_chassis.utils.metrics import get_metrics

        assert get_metrics() is get_metrics()

    def test_record_call_start_returns_float(self) -> None:
        from mcp_chassis.utils.metrics import get_metrics

        t = get_metrics().record_call_start("solveit_status")
        assert isinstance(t, float)
        assert t > 0

    def test_record_call_end_does_not_raise(self) -> None:
        from mcp_chassis.utils.metrics import get_metrics

        m = get_metrics()
        start = m.record_call_start("solveit_search")
        m.record_call_end("solveit_search", start)

    def test_record_call_end_with_error_does_not_raise(self) -> None:
        from mcp_chassis.utils.metrics import get_metrics

        m = get_metrics()
        start = m.record_call_start("solveit_get_technique")
        m.record_call_end("solveit_get_technique", start, fss_error_code="FSS_PARAM_INVALID")

    def test_record_call_start_returns_monotonic_time(self) -> None:
        from mcp_chassis.utils.metrics import get_metrics

        m = get_metrics()
        t1 = m.record_call_start("tool_a")
        time.sleep(0.001)
        t2 = m.record_call_start("tool_b")
        assert t2 >= t1

    def test_duration_is_positive(self) -> None:
        from mcp_chassis.utils.metrics import get_metrics

        m = get_metrics()
        start = m.record_call_start("tool")
        time.sleep(0.002)
        # duration_ms = (monotonic() - start) * 1000 — should be > 0
        duration_ms = (time.monotonic() - start) * 1000
        assert duration_ms > 0


class TestMCPMetricsWithOTel:
    """MCPMetrics with OTel enabled — verify counters and histograms are called."""

    @pytest.fixture()
    def mock_meter(self, monkeypatch: pytest.MonkeyPatch) -> dict:
        """Inject a mock OTel meter and return call tracking dicts."""
        from unittest.mock import MagicMock

        counts: dict[str, list] = {
            "call_counter": [],
            "duration_histogram": [],
            "error_counter": [],
        }

        mock_counter = MagicMock()
        mock_counter.add.side_effect = lambda n, attrs: counts["call_counter"].append((n, attrs))

        mock_histogram = MagicMock()
        mock_histogram.record.side_effect = lambda n, attrs: counts["duration_histogram"].append(
            (n, attrs)
        )
        mock_err_counter = MagicMock()
        mock_err_counter.add.side_effect = lambda n, attrs: counts["error_counter"].append(
            (n, attrs)
        )

        mock_meter_obj = MagicMock()
        mock_meter_obj.create_counter.side_effect = lambda *a, **kw: (
            mock_counter if "calls" in a[0] else mock_err_counter
        )
        mock_meter_obj.create_histogram.return_value = mock_histogram

        mock_telemetry = MagicMock()
        mock_telemetry.enabled = True
        mock_telemetry.get_meter.return_value = mock_meter_obj

        monkeypatch.setattr(
            "mcp_chassis.utils.telemetry.get_telemetry",
            lambda: mock_telemetry,
        )

        return counts

    def test_call_counter_incremented_on_start(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock, patch

        mock_counter = MagicMock()
        mock_histogram = MagicMock()
        mock_err_counter = MagicMock()

        mock_meter_obj = MagicMock()

        def create_counter(name: str, **kw: object) -> MagicMock:
            if "calls" in name:
                return mock_counter
            return mock_err_counter

        mock_meter_obj.create_counter.side_effect = create_counter
        mock_meter_obj.create_histogram.return_value = mock_histogram

        mock_telemetry = MagicMock()
        mock_telemetry.enabled = True
        mock_telemetry.get_meter.return_value = mock_meter_obj

        with patch("mcp_chassis.utils.telemetry.get_telemetry", return_value=mock_telemetry):
            from mcp_chassis.utils.metrics import MCPMetrics

            m = MCPMetrics()
            m.record_call_start("solveit_status")

        mock_counter.add.assert_called_once_with(1, {"tool.name": "solveit_status"})

    def test_duration_histogram_recorded_on_end(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock, patch

        mock_counter = MagicMock()
        mock_histogram = MagicMock()
        mock_err_counter = MagicMock()
        mock_meter_obj = MagicMock()

        def create_counter(name: str, **kw: object) -> MagicMock:
            return mock_counter if "calls" in name else mock_err_counter

        mock_meter_obj.create_counter.side_effect = create_counter
        mock_meter_obj.create_histogram.return_value = mock_histogram
        mock_telemetry = MagicMock()
        mock_telemetry.enabled = True
        mock_telemetry.get_meter.return_value = mock_meter_obj

        with patch("mcp_chassis.utils.telemetry.get_telemetry", return_value=mock_telemetry):
            from mcp_chassis.utils.metrics import MCPMetrics

            m = MCPMetrics()
            start = m.record_call_start("solveit_search")
            m.record_call_end("solveit_search", start)

        mock_histogram.record.assert_called_once()
        call_args = mock_histogram.record.call_args
        duration_ms = call_args[0][0]
        assert duration_ms >= 0
        assert call_args[0][1] == {"tool.name": "solveit_search"}

    def test_error_counter_incremented_on_error_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock, patch

        mock_counter = MagicMock()
        mock_histogram = MagicMock()
        mock_err_counter = MagicMock()
        mock_meter_obj = MagicMock()

        def create_counter(name: str, **kw: object) -> MagicMock:
            return mock_counter if "calls" in name else mock_err_counter

        mock_meter_obj.create_counter.side_effect = create_counter
        mock_meter_obj.create_histogram.return_value = mock_histogram
        mock_telemetry = MagicMock()
        mock_telemetry.enabled = True
        mock_telemetry.get_meter.return_value = mock_meter_obj

        with patch("mcp_chassis.utils.telemetry.get_telemetry", return_value=mock_telemetry):
            from mcp_chassis.utils.metrics import MCPMetrics

            m = MCPMetrics()
            start = m.record_call_start("solveit_get_technique")
            m.record_call_end("solveit_get_technique", start, fss_error_code="FSS_PARAM_INVALID")

        mock_err_counter.add.assert_called_once()
        call_args = mock_err_counter.add.call_args
        assert call_args[0][0] == 1
        assert call_args[0][1].get("fss.error_code") == "FSS_PARAM_INVALID"

    def test_no_error_counter_call_without_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock, patch

        mock_counter = MagicMock()
        mock_histogram = MagicMock()
        mock_err_counter = MagicMock()
        mock_meter_obj = MagicMock()

        def create_counter(name: str, **kw: object) -> MagicMock:
            return mock_counter if "calls" in name else mock_err_counter

        mock_meter_obj.create_counter.side_effect = create_counter
        mock_meter_obj.create_histogram.return_value = mock_histogram
        mock_telemetry = MagicMock()
        mock_telemetry.enabled = True
        mock_telemetry.get_meter.return_value = mock_meter_obj

        with patch("mcp_chassis.utils.telemetry.get_telemetry", return_value=mock_telemetry):
            from mcp_chassis.utils.metrics import MCPMetrics

            m = MCPMetrics()
            start = m.record_call_start("solveit_status")
            m.record_call_end("solveit_status", start)  # no error_code

        mock_err_counter.add.assert_not_called()

    def test_otel_disabled_meters_are_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock, patch

        mock_telemetry = MagicMock()
        mock_telemetry.enabled = False
        mock_telemetry.get_meter.return_value = None

        with patch("mcp_chassis.utils.telemetry.get_telemetry", return_value=mock_telemetry):
            from mcp_chassis.utils.metrics import MCPMetrics

            m = MCPMetrics()
            assert m._call_counter is None
            assert m._duration_histogram is None
            assert m._error_counter is None
