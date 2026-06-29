"""FSS per-request context variables for forensic provenance tracking.

Each variable is stored in an async-safe contextvars.ContextVar so it
propagates across await boundaries within a single request without
leaking between concurrent requests.

Set by server.py at the start of each tool dispatch call; read by
provenance.py when assembling the _provenance block.
"""

from __future__ import annotations

import contextvars
from typing import Any

# Transaction identifier — UUID v4 string (FSS-0002 §3.2)
fss_transaction_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_transaction_id", default=None
)

# CAI of canonically serialised tool call parameters (FSS-0005 §3.2)
fss_parameters_cai: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_parameters_cai", default=None
)

# CAI of serialised tool result; also used as artifact_id (FSS-0005 §3.2)
fss_result_cai: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_result_cai", default=None
)

# "success" | "error" | "partial" (FSS-0002 §3.1)
fss_result_status: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_result_status", default=None
)

# Investigation context — sourced from HTTP headers or None for stdio
fss_investigation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_investigation_id", default=None
)
fss_analyst_identity: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_analyst_identity", default=None
)
fss_agent_identity: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_agent_identity", default=None
)

# Authenticated client identity — set by auth middleware (FSS-0002 §7.1)
fss_client_identity: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_client_identity", default=None
)

# Request timestamp from X-Request-Timestamp header (replay prevention, L2-01)
fss_request_timestamp: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_request_timestamp", default=None
)

# Bearer token extracted from Authorization header (HTTP transport only)
# Consumed by the auth middleware via request_context["token"].
fss_auth_token: contextvars.ContextVar[str] = contextvars.ContextVar(
    "fss_auth_token", default=""
)

# Internal: Token list for resetting all vars after each dispatch
_ALL_VARS: tuple[contextvars.ContextVar[Any], ...] = (
    fss_transaction_id,
    fss_parameters_cai,
    fss_result_cai,
    fss_result_status,
    fss_investigation_id,
    fss_analyst_identity,
    fss_agent_identity,
    fss_client_identity,
    fss_request_timestamp,
    fss_auth_token,
)


def reset_fss_context(tokens: list[contextvars.Token[Any]]) -> None:
    """Reset all FSS context vars using the tokens from set() calls.

    Call this after each dispatch to prevent values leaking into the
    next concurrent request sharing the same task context.

    Args:
        tokens: List of Token objects returned by ContextVar.set() calls.
    """
    for token in tokens:
        token.var.reset(token)


__all__ = [
    "fss_agent_identity",
    "fss_analyst_identity",
    "fss_auth_token",
    "fss_client_identity",
    "fss_investigation_id",
    "fss_parameters_cai",
    "fss_result_cai",
    "fss_result_status",
    "fss_transaction_id",
    "reset_fss_context",
]
