"""FSS provenance record builder (FSS-0004 §3.1).

Reads FSS context variables and assembles the complete _provenance dict
that is embedded in every tool response. Profile A servers embed the
record in the tool response; Profile B/C servers must additionally write
it to an external tamper-evident audit log.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from mcp_chassis.utils.fss_context import (
    fss_agent_identity,
    fss_analyst_identity,
    fss_client_identity,
    fss_investigation_id,
    fss_parameters_cai,
    fss_result_cai,
    fss_result_status,
    fss_transaction_id,
)

logger = logging.getLogger(__name__)


def build_provenance_record(
    tool_name: str,
    tool_version: str = "0.0.0",
    kb_version_id: str | None = None,
    kb_version: str | None = None,
) -> dict[str, Any]:
    """Build a complete FSS-0004 §3.1 provenance record.

    Reads all fss_* context variables set by server.py during dispatch
    and assembles the provenance dict. Optionally signs it if a signing
    key is configured (FSS-0005 §6).

    Args:
        tool_name: Exact registered name of the tool.
        tool_version: Semantic version of the tool implementation.
        kb_version_id: CAI of the active KB snapshot (Profile A/B).
        kb_version: Human-readable KB version label for retrieval.

    Returns:
        Dict with all required FSS provenance fields.
    """
    import os
    result_status = fss_result_status.get() or "error"  # pessimistic default
    forensic_metadata = os.environ.get("FORENSIC_METADATA", "false").lower() == "true"
    evidentiary = "evidentiary" if (result_status == "success" and forensic_metadata) else "non-evidentiary"  # noqa: E501

    record: dict[str, Any] = {
        "transaction_id":     fss_transaction_id.get(),
        "tool_name":          tool_name,
        "tool_version":       tool_version,
        "kb_version_id":      kb_version_id,
        "kb_version":         kb_version,
        "parameters_cai":     fss_parameters_cai.get(),
        "artifact_id":        fss_result_cai.get(),    # same value as result_cai
        "result_cai":         fss_result_cai.get(),
        "timestamp_utc":      datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "result_status":      result_status,
        "evidentiary_status": evidentiary,
        "client_identity":    fss_client_identity.get(),
        "investigation_id":   fss_investigation_id.get(),
        "analyst_identity":   fss_analyst_identity.get(),
        "agent_identity":     fss_agent_identity.get(),
    }

    # Optional Ed25519 signature (FSS-0005 §6, required for Level 3)
    try:
        from mcp_chassis.utils.integrity import load_signing_key, sign_provenance
        key = load_signing_key()
        if key is not None:
            record["signature"] = sign_provenance(record, key)
    except Exception as exc:
        logger.debug("Provenance signing skipped: %s", exc)

    return record


__all__ = ["build_provenance_record"]
