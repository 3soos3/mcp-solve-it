"""Unit tests for mcp_chassis.logging_config module."""

from __future__ import annotations

import json
import logging
from io import StringIO

import pytest

from mcp_chassis.logging_config import JSONFormatter


class TestJSONFormatterSafeMessage:
    """Tests for _safe_message newline handling."""

    def test_newlines_stripped_from_message(self) -> None:
        """Newlines in log messages should be replaced to ensure single-line JSON."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="line1\nline2\nline3",
            args=(),
            exc_info=None,
        )
        safe = formatter._safe_message(record)
        assert "\n" not in safe

    def test_tabs_preserved_in_message(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="col1\tcol2",
            args=(),
            exc_info=None,
        )
        safe = formatter._safe_message(record)
        assert "\t" in safe

    def test_control_chars_stripped(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello\x01\x02world",
            args=(),
            exc_info=None,
        )
        safe = formatter._safe_message(record)
        assert "\x01" not in safe
        assert "\x02" not in safe
        assert "helloworld" == safe


class TestSecurityLogger:
    """Tests for get_security_logger and log_security_event (FSS-0003 §8.4, L2-02)."""

    @pytest.fixture(autouse=True)
    def reset_security_logger(self) -> None:
        """Reset the module-level singleton between tests."""
        import mcp_chassis.logging_config as lc
        original = lc._security_logger
        lc._security_logger = None
        yield
        lc._security_logger = original

    def test_get_security_logger_returns_logger(self) -> None:
        from mcp_chassis.logging_config import get_security_logger
        logger = get_security_logger()
        assert isinstance(logger, logging.Logger)
        assert logger.name == "mcp_chassis.security"

    def test_security_logger_does_not_propagate(self) -> None:
        from mcp_chassis.logging_config import get_security_logger
        logger = get_security_logger()
        assert logger.propagate is False

    def test_security_logger_is_singleton(self) -> None:
        from mcp_chassis.logging_config import get_security_logger
        assert get_security_logger() is get_security_logger()

    def test_security_logger_routes_to_stderr_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MCP_SECURITY_LOG_PATH", raising=False)
        from mcp_chassis.logging_config import get_security_logger
        logger = get_security_logger()
        handler_types = [type(h).__name__ for h in logger.handlers]
        assert "StreamHandler" in handler_types

    def test_security_logger_routes_to_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        import pathlib
        log_file = pathlib.Path(str(tmp_path)) / "security.log"
        monkeypatch.setenv("MCP_SECURITY_LOG_PATH", str(log_file))
        from mcp_chassis.logging_config import get_security_logger
        logger = get_security_logger()
        handler_types = [type(h).__name__ for h in logger.handlers]
        assert "FileHandler" in handler_types

    def test_log_security_event_emits_json(self) -> None:
        from mcp_chassis.logging_config import get_security_logger, log_security_event

        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(JSONFormatter())
        handler.setLevel(logging.WARNING)
        logger = get_security_logger()
        logger.addHandler(handler)

        log_security_event(
            "auth_failure",
            tool_name="solveit_status",
            error_detail="Missing Bearer token",
            transaction_id="abc-123",
        )

        output = buf.getvalue().strip()
        assert output, "Expected log output"
        # The outer log record message should be parseable JSON
        data = json.loads(output)
        assert "auth_failure" in str(data)

    def test_log_security_event_contains_required_fields(self) -> None:
        from mcp_chassis.logging_config import get_security_logger, log_security_event

        emitted: list[str] = []

        class CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                emitted.append(record.getMessage())

        logger = get_security_logger()
        handler = CapturingHandler()
        handler.setLevel(logging.WARNING)
        logger.addHandler(handler)

        log_security_event(
            "rate_limit_exceeded",
            tool_name="solveit_search",
            client_ip="192.168.1.1",
            error_detail="60 RPM exceeded",
            transaction_id="txn-456",
        )

        assert emitted, "Expected at least one log record"
        record_data = json.loads(emitted[-1])
        assert record_data["event_type"] == "rate_limit_exceeded"
        assert record_data["tool_name"] == "solveit_search"
        assert record_data["error_detail"] == "60 RPM exceeded"
        assert record_data["transaction_id"] == "txn-456"
        assert "timestamp_utc" in record_data

    def test_log_security_event_timestamp_is_utc(self) -> None:
        from mcp_chassis.logging_config import get_security_logger, log_security_event

        emitted: list[str] = []

        class CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                emitted.append(record.getMessage())

        logger = get_security_logger()
        handler = CapturingHandler()
        handler.setLevel(logging.WARNING)
        logger.addHandler(handler)

        log_security_event("auth_failure")
        record_data = json.loads(emitted[-1])
        ts = record_data.get("timestamp_utc", "")
        assert ts.endswith("+00:00") or ts.endswith("Z"), \
            f"Timestamp must be UTC: {ts}"

    def test_log_security_event_does_not_propagate_to_root(self) -> None:
        """Security events must not appear in the main application log."""
        from mcp_chassis.logging_config import log_security_event

        root_records: list[logging.LogRecord] = []

        class RootCapture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                root_records.append(record)

        root_handler = RootCapture()
        logging.getLogger().addHandler(root_handler)
        try:
            log_security_event("replay_rejected", error_detail="Timestamp out of window")
        finally:
            logging.getLogger().removeHandler(root_handler)

        # The security logger has propagate=False — nothing should reach the root
        security_records = [
            r for r in root_records
            if r.name == "mcp_chassis.security"
        ]
        assert not security_records, \
            "Security events must not propagate to the root logger"

    @pytest.mark.parametrize("event_type", [
        "auth_failure",
        "auth_denied",
        "rate_limit_exceeded",
        "schema_validation_failure",
        "replay_rejected",
        "tls_error",
    ])
    def test_all_documented_event_types_accepted(self, event_type: str) -> None:
        from mcp_chassis.logging_config import log_security_event
        # Must not raise for any documented event type
        log_security_event(event_type, error_detail="test")
