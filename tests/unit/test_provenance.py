"""Unit tests for mcp_chassis.utils.provenance — _provenance record (FSS-0004)."""

from __future__ import annotations

import pytest

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
from mcp_chassis.utils.provenance import build_provenance_record

# Required FSS-0004 §3.1 provenance fields
_REQUIRED_FIELDS = {
    "transaction_id",
    "tool_name",
    "tool_version",
    "kb_version_id",
    "kb_version",
    "parameters_cai",
    "artifact_id",
    "result_cai",
    "timestamp_utc",
    "result_status",
    "evidentiary_status",
    "client_identity",
    "investigation_id",
    "analyst_identity",
    "agent_identity",
}


def _set_context(
    *,
    transaction_id: str = "test-uuid-1234",
    parameters_cai: str = "sha2-256:aabbcc",
    result_cai: str = "sha2-256:ddeeff",
    result_status: str = "success",
    investigation_id: str | None = None,
    analyst_identity: str | None = None,
    agent_identity: str | None = None,
    client_identity: str | None = None,
) -> None:
    fss_transaction_id.set(transaction_id)
    fss_parameters_cai.set(parameters_cai)
    fss_result_cai.set(result_cai)
    fss_result_status.set(result_status)
    fss_investigation_id.set(investigation_id)
    fss_analyst_identity.set(analyst_identity)
    fss_agent_identity.set(agent_identity)
    fss_client_identity.set(client_identity)


def _clear_context() -> None:
    for var in (
        fss_transaction_id,
        fss_parameters_cai,
        fss_result_cai,
        fss_result_status,
        fss_investigation_id,
        fss_analyst_identity,
        fss_agent_identity,
        fss_client_identity,
    ):
        var.set(None)


class TestBuildProvenanceRecord:
    """Tests for build_provenance_record — FSS-0004 §3.1 compliance."""

    def setup_method(self) -> None:
        _set_context()

    def teardown_method(self) -> None:
        _clear_context()

    def test_all_required_fields_present(self) -> None:
        record = build_provenance_record("solveit_search", "1.0.0")
        missing = _REQUIRED_FIELDS - set(record.keys())
        assert not missing, f"Missing required FSS-0004 fields: {missing}"

    def test_tool_name_in_record(self) -> None:
        record = build_provenance_record("solveit_get_technique", "1.0.0")
        assert record["tool_name"] == "solveit_get_technique"

    def test_tool_version_in_record(self) -> None:
        record = build_provenance_record("tool", "2.3.4")
        assert record["tool_version"] == "2.3.4"

    def test_transaction_id_from_context(self) -> None:
        fss_transaction_id.set("my-uuid-4")
        record = build_provenance_record("tool", "1.0.0")
        assert record["transaction_id"] == "my-uuid-4"

    def test_parameters_cai_from_context(self) -> None:
        fss_parameters_cai.set("sha2-256:params-hash")
        record = build_provenance_record("tool", "1.0.0")
        assert record["parameters_cai"] == "sha2-256:params-hash"

    def test_artifact_id_equals_result_cai(self) -> None:
        fss_result_cai.set("sha2-256:result-hash")
        record = build_provenance_record("tool", "1.0.0")
        assert record["artifact_id"] == "sha2-256:result-hash"
        assert record["result_cai"] == "sha2-256:result-hash"
        assert record["artifact_id"] == record["result_cai"]

    def test_timestamp_utc_present_and_format(self) -> None:
        record = build_provenance_record("tool", "1.0.0")
        ts = record["timestamp_utc"]
        assert isinstance(ts, str)
        assert "T" in ts  # ISO 8601
        assert ts.endswith("Z") or "+" in ts  # timezone info

    def test_kb_version_id_passed_through(self) -> None:
        record = build_provenance_record(
            "tool",
            "1.0.0",
            kb_version_id="sha2-256:kb-hash",
            kb_version="solve-it-v2025.10",
        )
        assert record["kb_version_id"] == "sha2-256:kb-hash"
        assert record["kb_version"] == "solve-it-v2025.10"

    def test_kb_version_id_none_when_not_provided(self) -> None:
        record = build_provenance_record("tool", "1.0.0")
        assert record["kb_version_id"] is None
        assert record["kb_version"] is None


class TestEvidentiaryStatus:
    """Tests for evidentiary_status based on result_status."""

    def teardown_method(self) -> None:
        _clear_context()

    def test_success_is_evidentiary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORENSIC_METADATA", "true")
        _set_context(result_status="success")
        record = build_provenance_record("tool", "1.0.0")
        assert record["evidentiary_status"] == "evidentiary"
        assert record["result_status"] == "success"

    def test_success_without_forensic_metadata_is_non_evidentiary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FORENSIC_METADATA", "false")
        _set_context(result_status="success")
        record = build_provenance_record("tool", "1.0.0")
        assert record["evidentiary_status"] == "non-evidentiary"

    def test_error_is_non_evidentiary(self) -> None:
        _set_context(result_status="error")
        record = build_provenance_record("tool", "1.0.0")
        assert record["evidentiary_status"] == "non-evidentiary"

    def test_partial_is_non_evidentiary(self) -> None:
        _set_context(result_status="partial")
        record = build_provenance_record("tool", "1.0.0")
        assert record["evidentiary_status"] == "non-evidentiary"

    def test_default_status_non_evidentiary(self) -> None:
        # No status set — pessimistic default
        _clear_context()
        record = build_provenance_record("tool", "1.0.0")
        assert record["evidentiary_status"] == "non-evidentiary"


class TestInvestigationContext:
    """Tests for investigation context fields from FSS context vars."""

    def teardown_method(self) -> None:
        _clear_context()

    def test_investigation_id_from_context(self) -> None:
        _set_context(investigation_id="inv-uuid-9")
        record = build_provenance_record("tool", "1.0.0")
        assert record["investigation_id"] == "inv-uuid-9"

    def test_analyst_identity_from_context(self) -> None:
        _set_context(analyst_identity="J. de Vries")
        record = build_provenance_record("tool", "1.0.0")
        assert record["analyst_identity"] == "J. de Vries"

    def test_agent_identity_from_context(self) -> None:
        _set_context(agent_identity="claude-sonnet/4.6")
        record = build_provenance_record("tool", "1.0.0")
        assert record["agent_identity"] == "claude-sonnet/4.6"

    def test_client_identity_from_context(self) -> None:
        _set_context(client_identity="analyst-token-1")
        record = build_provenance_record("tool", "1.0.0")
        assert record["client_identity"] == "analyst-token-1"

    def test_null_when_not_set(self) -> None:
        _clear_context()
        record = build_provenance_record("tool", "1.0.0")
        assert record["investigation_id"] is None
        assert record["analyst_identity"] is None
        assert record["agent_identity"] is None
        assert record["client_identity"] is None


class TestSignatureField:
    """Tests for optional Ed25519 signature in provenance record."""

    def teardown_method(self) -> None:
        _clear_context()

    def test_signature_absent_when_no_key_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FSS_SIGNING_KEY_PATH", raising=False)
        monkeypatch.delenv("FSS_SIGNING_KEY_B64", raising=False)
        _set_context(result_status="success")
        record = build_provenance_record("tool", "1.0.0")
        assert "signature" not in record

    def test_signature_present_when_key_configured(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("cryptography", reason="cryptography not installed")
        import pathlib

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
        )

        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        key_file = pathlib.Path(str(tmp_path)) / "key.pem"
        key_file.write_bytes(pem)

        monkeypatch.setenv("FSS_SIGNING_KEY_PATH", str(key_file))
        monkeypatch.delenv("FSS_SIGNING_KEY_B64", raising=False)

        _set_context(
            transaction_id="t-uuid",
            result_cai="sha2-256:result",
            result_status="success",
        )
        record = build_provenance_record("solveit_search", "1.0.0")
        assert "signature" in record
        assert isinstance(record["signature"], str)
        assert len(record["signature"]) > 0
