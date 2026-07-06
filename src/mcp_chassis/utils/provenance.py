"""FSS provenance record builder (FSS-0004 §3.1).

Reads FSS context variables and assembles the complete provenance dict
that is embedded in every tool response via _meta._fss.provenance
(FSS-0010 §3.2). Profile A servers embed the record in the tool response;
Profile B/C servers must additionally write it to an external tamper-evident
audit log.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from mcp_chassis.utils.fss_context import (
    fss_analyst_identity,
    fss_client_identity,
    fss_fit_aud,
    fss_fit_issuer,
    fss_fit_jti,
    fss_fit_legal_authority,
    fss_fit_purpose,
    fss_fit_valid_until,
    fss_investigation_id,
    fss_investigation_id_verified,
    fss_invocation_type,
    fss_llm_model,
    fss_llm_provider,
    fss_mcp_client,
    fss_parameters_cai,
    fss_result_cai,
    fss_result_status,
    fss_tool_authorization_verified,
    fss_transaction_id,
)

logger = logging.getLogger(__name__)

_DEFAULT_INVOCATION_TYPE = "agent_supervised"
_VALID_INVOCATION_TYPES = {"human_direct", "agent_supervised", "agent_autonomous"}


def _get_invocation_type() -> str:
    """Return the effective invocation_type for this request.

    Priority: per-request context var (set from _meta) → server env var → default.
    """
    ctx_val = fss_invocation_type.get()
    if ctx_val and ctx_val in _VALID_INVOCATION_TYPES:
        return ctx_val
    env_val = os.environ.get("MCP_INVOCATION_TYPE", _DEFAULT_INVOCATION_TYPE)
    return env_val if env_val in _VALID_INVOCATION_TYPES else _DEFAULT_INVOCATION_TYPE


def build_provenance_record(
    tool_name: str,
    tool_version: str = "0.0.0",
    kb_version_id: str | None = None,
    kb_version: str | None = None,
) -> dict[str, Any]:
    """Build a complete FSS-0004 §3.1 provenance record.

    Reads all fss_* context variables set by server.py during dispatch
    and assembles the provenance dict. Signs when FSS_SIGNING=true or
    FSS_METADATA=true (FSS-0005 §6).

    Args:
        tool_name: Exact registered name of the tool.
        tool_version: Semantic version of the tool implementation.
        kb_version_id: CAI of the active KB snapshot (Profile A/B).
        kb_version: Human-readable KB version label for retrieval.

    Returns:
        Dict with all required FSS provenance fields.
    """
    import mcp_chassis

    fss_metadata = os.environ.get("FSS_METADATA", "false").lower() == "true"
    client_identity = fss_client_identity.get()
    result_status = fss_result_status.get() or "error"  # pessimistic default

    # evidentiary requires FSS_METADATA=true AND a verified client_identity (FSS-0004 §3.1)
    evidentiary = (
        "evidentiary"
        if (fss_metadata and client_identity)
        else "non-evidentiary"
    )

    # analyst_identity_binding: "federated" when analyst identity is tied to verified
    # OAuth client_identity; "asserted" when it is a self-reported _meta claim
    analyst_identity_binding = "federated" if client_identity else "asserted"

    # software_identity: derived from mcp_client (clientInfo.name/version) per FSS-0010 §3.3
    mcp_client = fss_mcp_client.get()
    software_identity = mcp_client  # already formatted as "name/version"

    record: dict[str, Any] = {
        "artifact_id": fss_result_cai.get(),
        "transaction_id": fss_transaction_id.get(),
        "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "tool_name": tool_name,
        "tool_version": tool_version,
        "kb_version_id": kb_version_id,
        "kb_version": kb_version,
        "parameters_cai": fss_parameters_cai.get(),
        "result_cai": fss_result_cai.get(),
        "result_status": result_status,
        "evidentiary_status": evidentiary,
        "invocation_type": _get_invocation_type(),
        "analyst_identity": fss_analyst_identity.get(),
        "analyst_identity_binding": analyst_identity_binding,
        "software_identity": software_identity,
        "llm_model": fss_llm_model.get(),
        "llm_provider": fss_llm_provider.get(),
        "mcp_client": mcp_client,
        "investigation_id": fss_investigation_id.get(),
        "client_identity": client_identity,
        "server_version": mcp_chassis.__version__,
        "image_digest": os.environ.get("IMAGE_DIGEST") or None,
        "assessed_under": (
            os.environ.get("FSS_ASSESSED_UNDER")
            or f"FSS-0009v{os.environ.get('FSS_SPEC_VERSION', '1.0')}"
               f"L{os.environ.get('FSS_CONFORMANCE_LEVEL', '1')}"
        ),
        "fit_jti": fss_fit_jti.get(),
        "fit_issuer": fss_fit_issuer.get(),
        "fit_valid_until": fss_fit_valid_until.get(),
        "fit_aud": fss_fit_aud.get(),
        "legal_authority": fss_fit_legal_authority.get(),
        "purpose": fss_fit_purpose.get(),
        "investigation_id_verified": fss_investigation_id_verified.get(),
        "tool_authorization_verified": fss_tool_authorization_verified.get(),
    }

    # Ed25519 signatures — only for success responses (FSS-0005 §6.2:
    # "MUST sign … for each successful tool result").  Error responses have
    # result_cai=null which cannot be independently verified by external
    # parties, so they are excluded from the signing scope.
    if result_status == "success":
        try:
            from mcp_chassis.utils.integrity import (
                load_signing_key,
                sign_provenance,
                sign_provenance_full,
            )

            key = load_signing_key()
            if key is not None:
                record["data_signature"] = sign_provenance(record, key)
                record["provenance_signature"] = sign_provenance_full(record, key)
        except Exception as exc:
            logger.debug("Provenance signing skipped: %s", exc)

    return record


__all__ = ["build_provenance_record"]
