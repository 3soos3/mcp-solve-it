"""Error types for the MCP Chassis server.

All errors carry a correlation ID for log tracing.
FSSError provides the FSS-0002 §6.3 error taxonomy required for
forensic MCP servers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

# ── FSS error taxonomy (FSS-0002 §6.3) ────────────────────────────────

FSS_AUTH_REQUIRED = "FSS_AUTH_REQUIRED"
FSS_AUTH_DENIED = "FSS_AUTH_DENIED"
FSS_PARAM_INVALID = "FSS_PARAM_INVALID"
FSS_TOOL_UNAVAILABLE = "FSS_TOOL_UNAVAILABLE"
FSS_DATASET_UNAVAILABLE = "FSS_DATASET_UNAVAILABLE"
FSS_EXECUTION_INTERRUPTED = "FSS_EXECUTION_INTERRUPTED"
FSS_EXECUTION_FAILED = "FSS_EXECUTION_FAILED"
FSS_INTERNAL_ERROR = "FSS_INTERNAL_ERROR"


@dataclass
class FSSError(Exception):
    """FSS-compliant error response (FSS-0002 §6.1–6.3).

    All FSS error responses carry a transaction_id for audit trail
    correlation and evidentiary_status: non-evidentiary.

    Attributes:
        error_code: FSS error code (FSS_* constant).
        error_message: Human-readable error description.
        transaction_id: UUID v4 of the current transaction (may be None
            if the error occurs before the transaction ID is generated).
        partial_result: Whether a partial result is available.
        partial_data: Optional partial result data.
    """

    error_code: str
    error_message: str
    transaction_id: str | None = field(default=None)
    partial_result: bool = field(default=False)
    partial_data: Any = field(default=None)

    def __post_init__(self) -> None:
        """Initialize as Exception with the error message."""
        super().__init__(self.error_message)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to FSS error response dict."""
        d: dict[str, Any] = {
            "error_code": self.error_code,
            "error_message": self.error_message,
            "transaction_id": self.transaction_id,
            "partial_result": self.partial_result,
            "evidentiary_status": "non-evidentiary",
        }
        if self.partial_result and self.partial_data is not None:
            d["partial_data"] = self.partial_data
        return d


class ChassisError(Exception):
    """Base error class with correlation ID for log tracing.

    Args:
        message: Human-readable error description.
        code: Machine-readable error code string.
    """

    def __init__(self, message: str, code: str) -> None:
        """Initialize the error with message, code, and a generated correlation ID."""
        self.correlation_id = uuid.uuid4().hex[:12]
        self.code = code
        super().__init__(message)

    def __str__(self) -> str:
        """Return string with correlation ID appended."""
        return f"{super().__str__()} [correlation_id={self.correlation_id}]"


class ValidationError(ChassisError):
    """Raised when tool input fails validation.

    Args:
        message: Description of the validation failure.
        code: Error code, defaults to 'VALIDATION_ERROR'.
    """

    def __init__(self, message: str, code: str = "VALIDATION_ERROR") -> None:
        """Initialize validation error."""
        super().__init__(message, code)


class SanitizationError(ChassisError):
    """Raised when input sanitization encounters an unrecoverable issue.

    Args:
        message: Description of the sanitization failure.
        code: Error code, defaults to 'SANITIZATION_ERROR'.
    """

    def __init__(self, message: str, code: str = "SANITIZATION_ERROR") -> None:
        """Initialize sanitization error."""
        super().__init__(message, code)


class RateLimitError(ChassisError):
    """Raised when a rate limit is exceeded.

    Args:
        message: Description including retry-after information.
        code: Error code, defaults to 'RATE_LIMIT_EXCEEDED'.
        retry_after: Seconds until the client may retry.
    """

    def __init__(
        self,
        message: str,
        code: str = "RATE_LIMIT_EXCEEDED",
        retry_after: float = 0.0,
    ) -> None:
        """Initialize rate limit error with optional retry-after hint."""
        self.retry_after = retry_after
        super().__init__(message, code)


class IOLimitError(ChassisError):
    """Raised when a request or response exceeds its configured size limit.

    Args:
        message: Description of which limit was exceeded.
        code: Error code, defaults to 'IO_LIMIT_EXCEEDED'.
    """

    def __init__(self, message: str, code: str = "IO_LIMIT_EXCEEDED") -> None:
        """Initialize I/O limit error."""
        super().__init__(message, code)


class AuthError(ChassisError):
    """Raised when authentication or authorization fails.

    Args:
        message: Description of the auth failure.
        code: Error code, defaults to 'AUTH_ERROR'.
    """

    def __init__(self, message: str, code: str = "AUTH_ERROR") -> None:
        """Initialize auth error."""
        super().__init__(message, code)


class ExtensionError(ChassisError):
    """Raised when an extension fails to load or register.

    Args:
        message: Description of the extension failure.
        code: Error code, defaults to 'EXTENSION_ERROR'.
    """

    def __init__(self, message: str, code: str = "EXTENSION_ERROR") -> None:
        """Initialize extension error."""
        super().__init__(message, code)
