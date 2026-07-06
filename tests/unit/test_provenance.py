"""Unit tests for mcp_chassis.utils.provenance — _provenance record (FSS-0004)."""

from __future__ import annotations

import pytest

from mcp_chassis.utils.fss_context import (
    fss_analyst_identity,
    fss_client_identity,
    fss_investigation_id,
    fss_llm_model,
    fss_llm_provider,
    fss_mcp_client,
    fss_parameters_cai,
    fss_result_cai,
    fss_result_status,
    fss_transaction_id,
)
from mcp_chassis.utils.provenance import build_provenance_record

# Required FSS-0004 §3.1 / FSS-0009 A.1.1 provenance fields (Level 1)
_REQUIRED_FIELDS = {
    "artifact_id",
    "transaction_id",
    "timestamp_utc",
    "tool_name",
    "tool_version",
    "kb_version_id",
    "kb_version",
    "parameters_cai",
    "result_cai",
    "result_status",
    "evidentiary_status",
    "invocation_type",
    "analyst_identity",
    "analyst_identity_binding",
    "investigation_id",
    "client_identity",
    "server_version",
}


def _set_context(
    *,
    transaction_id: str = "test-uuid-1234",
    parameters_cai: str = "sha2-256:aabbcc",
    result_cai: str = "sha2-256:ddeeff",
    result_status: str = "success",
    investigation_id: str | None = None,
    analyst_identity: str | None = None,
    client_identity: str | None = None,
    llm_model: str | None = None,
    llm_provider: str | None = None,
    mcp_client: str | None = None,
) -> None:
    fss_transaction_id.set(transaction_id)
    fss_parameters_cai.set(parameters_cai)
    fss_result_cai.set(result_cai)
    fss_result_status.set(result_status)
    fss_investigation_id.set(investigation_id)
    fss_analyst_identity.set(analyst_identity)
    fss_client_identity.set(client_identity)
    fss_llm_model.set(llm_model)
    fss_llm_provider.set(llm_provider)
    fss_mcp_client.set(mcp_client)


def _clear_context() -> None:
    for var in (
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

    def test_no_agent_identity_field(self) -> None:
        record = build_provenance_record("tool", "1.0.0")
        assert "agent_identity" not in record

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
        assert "T" in ts
        assert ts.endswith("Z") or "+" in ts

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

    def test_server_version_present(self) -> None:
        record = build_provenance_record("tool", "1.0.0")
        assert isinstance(record["server_version"], str)
        assert len(record["server_version"]) > 0

    def test_invocation_type_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MCP_INVOCATION_TYPE", raising=False)
        record = build_provenance_record("tool", "1.0.0")
        assert record["invocation_type"] == "agent_supervised"

    def test_invocation_type_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MCP_INVOCATION_TYPE", "human_direct")
        record = build_provenance_record("tool", "1.0.0")
        assert record["invocation_type"] == "human_direct"

    def test_invocation_type_invalid_env_uses_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MCP_INVOCATION_TYPE", "invalid_value")
        record = build_provenance_record("tool", "1.0.0")
        assert record["invocation_type"] == "agent_supervised"


class TestEvidentiaryStatus:
    """Tests for evidentiary_status — requires FSS_METADATA=true AND client_identity."""

    def teardown_method(self) -> None:
        _clear_context()

    def test_evidentiary_requires_fss_metadata_and_client_identity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FSS_METADATA", "true")
        _set_context(result_status="success", client_identity="user@example.org")
        record = build_provenance_record("tool", "1.0.0")
        assert record["evidentiary_status"] == "evidentiary"

    def test_evidentiary_false_without_client_identity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FSS_METADATA", "true")
        _set_context(result_status="success")  # no client_identity
        record = build_provenance_record("tool", "1.0.0")
        assert record["evidentiary_status"] == "non-evidentiary"

    def test_evidentiary_false_without_fss_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FSS_METADATA", "false")
        _set_context(result_status="success", client_identity="user@example.org")
        record = build_provenance_record("tool", "1.0.0")
        assert record["evidentiary_status"] == "non-evidentiary"

    def test_error_is_non_evidentiary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FSS_METADATA", "true")
        _set_context(result_status="error", client_identity="user@example.org")
        record = build_provenance_record("tool", "1.0.0")
        # evidentiary is based on FSS_METADATA + client_identity, not result_status
        assert record["evidentiary_status"] == "evidentiary"
        assert record["result_status"] == "error"

    def test_default_status_non_evidentiary(self) -> None:
        _clear_context()
        record = build_provenance_record("tool", "1.0.0")
        assert record["evidentiary_status"] == "non-evidentiary"


class TestAnalystIdentityBinding:
    """Tests for analyst_identity_binding (FSS-0004 §3.1, FSS-0009 A.2.1)."""

    def teardown_method(self) -> None:
        _clear_context()

    def test_binding_asserted_without_client_identity(self) -> None:
        _set_context(analyst_identity="analyst@example.org")
        record = build_provenance_record("tool", "1.0.0")
        assert record["analyst_identity_binding"] == "asserted"

    def test_binding_federated_with_client_identity(self) -> None:
        _set_context(analyst_identity="analyst@example.org", client_identity="oauth-sub-123")
        record = build_provenance_record("tool", "1.0.0")
        assert record["analyst_identity_binding"] == "federated"

    def test_binding_asserted_when_no_analyst(self) -> None:
        _set_context()
        record = build_provenance_record("tool", "1.0.0")
        assert record["analyst_identity_binding"] == "asserted"


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

    def test_client_identity_from_context(self) -> None:
        _set_context(client_identity="analyst-token-1")
        record = build_provenance_record("tool", "1.0.0")
        assert record["client_identity"] == "analyst-token-1"

    def test_llm_fields_from_context(self) -> None:
        _set_context(llm_model="claude-opus-4", llm_provider="Anthropic")
        record = build_provenance_record("tool", "1.0.0")
        assert record["llm_model"] == "claude-opus-4"
        assert record["llm_provider"] == "Anthropic"

    def test_mcp_client_sets_software_identity(self) -> None:
        _set_context(mcp_client="solve-it/2.1.0")
        record = build_provenance_record("tool", "1.0.0")
        assert record["mcp_client"] == "solve-it/2.1.0"
        assert record["software_identity"] == "solve-it/2.1.0"

    def test_null_when_not_set(self) -> None:
        _clear_context()
        record = build_provenance_record("tool", "1.0.0")
        assert record["investigation_id"] is None
        assert record["analyst_identity"] is None
        assert record["client_identity"] is None
        assert record["llm_model"] is None
        assert record["llm_provider"] is None


class TestSignatureField:
    """Tests for optional Ed25519 data_signature in provenance record."""

    def teardown_method(self) -> None:
        _clear_context()

    def test_no_signature_when_signing_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FSS_SIGNING_KEY_PATH", raising=False)
        monkeypatch.delenv("FSS_SIGNING_KEY_B64", raising=False)
        monkeypatch.setenv("FSS_SIGNING", "false")
        monkeypatch.setenv("FSS_METADATA", "false")
        _set_context(result_status="success")
        record = build_provenance_record("tool", "1.0.0")
        assert "data_signature" not in record
        assert "signature" not in record

    def test_data_signature_present_when_key_configured(
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
        monkeypatch.setenv("FSS_SIGNING", "true")
        monkeypatch.setenv("FSS_METADATA", "false")

        _set_context(
            transaction_id="t-uuid",
            result_cai="sha2-256:result",
            result_status="success",
        )
        record = build_provenance_record("solveit_search", "1.0.0")
        assert "data_signature" in record
        assert "signature" not in record
        sig = record["data_signature"]
        assert isinstance(sig, dict)
        assert "value" in sig and "kid" in sig
        assert len(sig["value"]) > 0
        assert len(sig["kid"]) > 0

    def test_provenance_signature_present_in_evidentiary_mode(
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
        monkeypatch.setenv("FSS_METADATA", "true")

        _set_context(
            transaction_id="t-uuid",
            result_cai="sha2-256:result",
            result_status="success",
            client_identity="user@example.org",
        )
        record = build_provenance_record("solveit_search", "1.0.0")
        assert "data_signature" in record
        assert "provenance_signature" in record
        assert "signature" not in record
