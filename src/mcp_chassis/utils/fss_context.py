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

# Investigation context — sourced from _meta in tool arguments or HTTP headers
fss_investigation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_investigation_id", default=None
)
fss_analyst_identity: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_analyst_identity", default=None
)

# Authenticated client identity — set by auth middleware (FSS-0002 §7.1)
fss_client_identity: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_client_identity", default=None
)

# LLM context — sourced from _meta in tool arguments (per-call, unverified)
fss_llm_model: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_llm_model", default=None
)
fss_llm_provider: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_llm_provider", default=None
)

# MCP client identity from initialize handshake clientInfo.name/version (FSS-0010 §3.3)
fss_mcp_client: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_mcp_client", default=None
)

# Invocation type — set from MCP_INVOCATION_TYPE env var at server startup
# human_direct | agent_supervised | agent_autonomous (FSS-0002 §4.4)
fss_invocation_type: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_invocation_type", default=None
)

# Request timestamp from X-Request-Timestamp header (replay prevention, L2-01)
fss_request_timestamp: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_request_timestamp", default=None
)

# Bearer token extracted from Authorization header (HTTP transport only)
# Consumed by the auth middleware via request_context["token"].
fss_auth_token: contextvars.ContextVar[str] = contextvars.ContextVar("fss_auth_token", default="")

# FIT (Forensic Investigation Token) context vars (FSS-0006 §8)
fss_fit_token: contextvars.ContextVar[str] = contextvars.ContextVar("fss_fit_token", default="")
fss_fit_jti: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_fit_jti", default=None
)
fss_fit_issuer: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_fit_issuer", default=None
)
fss_fit_valid_until: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_fit_valid_until", default=None
)
fss_fit_aud: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_fit_aud", default=None
)
fss_fit_legal_authority: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_fit_legal_authority", default=None
)
fss_fit_purpose: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_fit_purpose", default=None
)
fss_investigation_id_verified: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "fss_investigation_id_verified", default=False
)
fss_tool_authorization_verified: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "fss_tool_authorization_verified", default=False
)

# MCP session identifier from Mcp-Session-Id header (FSS-0010 §3.5)
fss_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fss_session_id", default=None
)

# Internal: Token list for resetting all vars after each dispatch
_ALL_VARS: tuple[contextvars.ContextVar[Any], ...] = (
    fss_transaction_id,
    fss_parameters_cai,
    fss_result_cai,
    fss_result_status,
    fss_investigation_id,
    fss_analyst_identity,
    fss_client_identity,
    fss_llm_model,
    fss_llm_provider,
    fss_mcp_client,
    fss_invocation_type,
    fss_request_timestamp,
    fss_auth_token,
    fss_fit_token,
    fss_fit_jti,
    fss_fit_issuer,
    fss_fit_valid_until,
    fss_fit_aud,
    fss_fit_legal_authority,
    fss_fit_purpose,
    fss_investigation_id_verified,
    fss_tool_authorization_verified,
    fss_session_id,
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
    "fss_analyst_identity",
    "fss_auth_token",
    "fss_client_identity",
    "fss_fit_aud",
    "fss_fit_issuer",
    "fss_fit_jti",
    "fss_fit_legal_authority",
    "fss_fit_purpose",
    "fss_fit_token",
    "fss_fit_valid_until",
    "fss_investigation_id_verified",
    "fss_invocation_type",
    "fss_investigation_id",
    "fss_llm_model",
    "fss_llm_provider",
    "fss_mcp_client",
    "fss_parameters_cai",
    "fss_result_cai",
    "fss_result_status",
    "fss_tool_authorization_verified",
    "fss_transaction_id",
    "fss_session_id",
    "reset_fss_context",
]
