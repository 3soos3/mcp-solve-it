"""Logging configuration for the MCP Chassis server.

All log output goes to stderr; stdout is reserved for MCP JSON-RPC messages.
Uses a custom JSONFormatter for structured, machine-parseable output.
"""

import json
import logging
import sys
import time


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects.

    Output fields: timestamp (ISO 8601), level, logger, message,
    and any extras including correlation_id.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a JSON string.

        Args:
            record: The log record to format.

        Returns:
            A single-line JSON string.
        """
        log_obj: dict[str, object] = {
            "timestamp": self._format_time(record),
            "level": record.levelname,
            "logger": record.name,
            "message": self._safe_message(record),
        }

        # Include correlation_id if present
        if hasattr(record, "correlation_id"):
            log_obj["correlation_id"] = record.correlation_id

        # Include exc_info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj, ensure_ascii=False)

    def _format_time(self, record: logging.LogRecord) -> str:
        """Return ISO 8601 timestamp string.

        Args:
            record: The log record with created timestamp.

        Returns:
            ISO 8601 formatted timestamp.
        """
        ct = time.gmtime(record.created)
        return time.strftime("%Y-%m-%dT%H:%M:%S", ct) + f".{int(record.msecs):03d}Z"

    def _safe_message(self, record: logging.LogRecord) -> str:
        """Return the formatted message, stripping ASCII control characters.

        Args:
            record: The log record.

        Returns:
            Message string safe for JSON embedding.
        """
        msg = record.getMessage()
        # Strip ASCII control characters (including newlines) to ensure
        # single-line JSON output and prevent log injection.
        return "".join(ch for ch in msg if ch == "\t" or ord(ch) >= 32)


_SECURITY_LOGGER_NAME = "mcp_chassis.security"
_security_logger: logging.Logger | None = None


def get_security_logger() -> logging.Logger:
    """Return the dedicated security event logger.

    Security events (auth failures, rate limit violations, schema rejections,
    replay window rejections) are routed to this logger separately from
    application logs, satisfying FSS-0003 §8.4.

    The logger writes JSON to the path configured in MCP_SECURITY_LOG_PATH,
    or to stderr alongside application logs if that variable is unset.
    """
    global _security_logger
    if _security_logger is not None:
        return _security_logger

    import os

    _security_logger = logging.getLogger(_SECURITY_LOGGER_NAME)
    _security_logger.propagate = False

    log_path = os.environ.get("MCP_SECURITY_LOG_PATH", "")
    if log_path:
        handler: logging.Handler = logging.FileHandler(log_path, encoding="utf-8")
    else:
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(JSONFormatter())
    handler.setLevel(logging.WARNING)
    _security_logger.addHandler(handler)
    _security_logger.setLevel(logging.WARNING)

    return _security_logger


def log_security_event(
    event_type: str,
    *,
    tool_name: str = "",
    client_ip: str = "",
    error_detail: str = "",
    transaction_id: str = "",
) -> None:
    """Emit a structured security event to the security log.

    Args:
        event_type: One of: auth_failure, auth_denied, rate_limit_exceeded,
            schema_validation_failure, replay_rejected, tls_error.
        tool_name: Tool being invoked when the event occurred.
        client_ip: Remote IP address if available.
        error_detail: Human-readable detail about the event.
        transaction_id: FSS transaction ID if available.
    """
    import datetime

    sec_logger = get_security_logger()
    record = {
        "event_type": event_type,
        "timestamp_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "tool_name": tool_name,
        "client_ip": client_ip,
        "error_detail": error_detail,
        "transaction_id": transaction_id,
    }
    sec_logger.warning(
        json.dumps(record, ensure_ascii=False),
        extra={"correlation_id": transaction_id},
    )


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger for structured JSON output to stderr.

    Replaces any existing handlers on the root logger. All subsequent
    logging calls will emit single-line JSON to stderr. stdout is never
    written to by this configuration.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
            Case-insensitive.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONFormatter())
    handler.setLevel(numeric_level)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(numeric_level)
