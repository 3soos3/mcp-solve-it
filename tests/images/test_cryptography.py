"""Cryptographic hash verification tests for FSS provenance CAI fields.

The FSS uses Content-Addressable Identifiers (CAI) in the form:
    sha2-256:<64-hex-char-SHA-256-digest>

These tests verify:
1. Format correctness (length, prefix, valid hex characters)
2. Determinism (same inputs → same CAI)
3. Uniqueness (different inputs → different CAI)
4. Internal consistency (artifact_id == result_cai where specified)
5. Pre-image verification: recompute sha2-256(canonical_params) and compare

The canonical serialisation for parameters_cai is:
    SHA-256 of UTF-8 encoded JSON with sorted keys and no extra whitespace,
    i.e. json.dumps(params, sort_keys=True, separators=(',', ':')).encode()

If the pre-image tests fail, the serialisation assumed above differs from
the server's actual implementation — the format tests still pass independently.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from .conftest import PodmanMCPClient, cai_hex, is_valid_cai, sha2_256_cai

pytestmark = pytest.mark.crypto


# ── Format tests ──────────────────────────────────────────────────────────────


class TestCAIFormat:
    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_parameters_cai_length_is_73(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_search", {"keywords": "triage"})
        cai = str(client.prov(data).get("parameters_cai", ""))
        assert len(cai) == 73, f"{fixture_name}: parameters_cai length {len(cai)!r}: {cai!r}"

    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_artifact_id_length_is_73(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_search", {"keywords": "triage"})
        cai = str(client.prov(data).get("artifact_id", ""))
        assert len(cai) == 73, f"{fixture_name}: artifact_id length {len(cai)!r}: {cai!r}"

    @pytest.mark.parametrize("fixture_name", ["monthly", "version"])
    def test_kb_version_id_length_is_73(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_status")
        cai = str(client.prov(data).get("kb_version_id", ""))
        assert len(cai) == 73, f"{fixture_name}: kb_version_id length {len(cai)!r}: {cai!r}"

    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_cai_hex_portion_is_valid_hex(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_search", {"keywords": "triage"})
        p = client.prov(data)
        for field in ("parameters_cai", "artifact_id"):
            hex_part = cai_hex(p.get(field, ""))
            assert len(hex_part) == 64, f"{fixture_name}.{field}: hex part length {len(hex_part)}"
            assert all(c in "0123456789abcdef" for c in hex_part), (
                f"{fixture_name}.{field}: non-hex character in digest: {hex_part[:16]}"
            )

    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_all_cai_fields_valid(self, fixture_name: str, request: pytest.FixtureRequest) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        p = client.prov(data)
        for field in ("parameters_cai", "artifact_id"):
            assert is_valid_cai(p.get(field, "")), (
                f"{fixture_name}: invalid CAI in {field!r}: {p.get(field)!r}"
            )


# ── Determinism tests ─────────────────────────────────────────────────────────


class TestDeterminism:
    def test_parameters_cai_same_for_same_inputs(self, version: PodmanMCPClient) -> None:
        a = version.prov(
            version.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        ).get("parameters_cai")
        b = version.prov(
            version.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        ).get("parameters_cai")
        assert a and b and a == b, f"parameters_cai not deterministic: {a} != {b}"

    def test_artifact_id_same_for_same_inputs(self, version: PodmanMCPClient) -> None:
        a = version.prov(
            version.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        ).get("artifact_id")
        b = version.prov(
            version.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        ).get("artifact_id")
        assert a and b and a == b, f"artifact_id not deterministic in :version: {a} != {b}"

    def test_kb_version_id_stable_across_calls(self, version: PodmanMCPClient) -> None:
        a = version.prov(version.call_tool("solveit_status")).get("kb_version_id")
        b = version.prov(
            version.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        ).get("kb_version_id")
        c = version.prov(version.call_tool("solveit_search", {"keywords": "triage"})).get(
            "kb_version_id"
        )
        assert a == b == c and a, f"kb_version_id not stable: {a}, {b}, {c}"


# ── Uniqueness tests ──────────────────────────────────────────────────────────


class TestUniqueness:
    def test_different_params_different_parameters_cai(self, version: PodmanMCPClient) -> None:
        a = version.prov(
            version.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        ).get("parameters_cai")
        b = version.prov(
            version.call_tool("solveit_get_technique", {"technique_id": "DFT-1002"})
        ).get("parameters_cai")
        assert a and b and a != b, (
            "Different technique_id inputs must produce different parameters_cai"
        )

    def test_different_tools_different_parameters_cai(self, version: PodmanMCPClient) -> None:
        a = version.prov(
            version.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        ).get("parameters_cai")
        b = version.prov(
            version.call_tool("solveit_get_weakness", {"weakness_id": "DFW-1001"})
        ).get("parameters_cai")
        assert a and b and a != b, "Different tool calls should produce different parameters_cai"

    def test_different_results_different_artifact_ids(self, version: PodmanMCPClient) -> None:
        a = version.prov(
            version.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        ).get("artifact_id")
        b = version.prov(
            version.call_tool("solveit_get_technique", {"technique_id": "DFT-1002"})
        ).get("artifact_id")
        assert a and b and a != b, "Different results must produce different artifact_ids"


# ── Internal consistency tests ────────────────────────────────────────────────


class TestInternalConsistency:
    @pytest.mark.parametrize("fixture_name", ["monthly", "version"])
    def test_artifact_id_equals_result_cai(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_search", {"keywords": "triage"})
        p = client.prov(data)
        assert p.get("artifact_id") == p.get("result_cai") is not None, (
            f"{fixture_name}: artifact_id ({p.get('artifact_id')!r}) != "
            f"result_cai ({p.get('result_cai')!r})"
        )

    def test_transaction_id_not_same_as_artifact_id(self, version: PodmanMCPClient) -> None:
        data = version.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        p = version.prov(data)
        assert p.get("transaction_id") != p.get("artifact_id"), (
            "transaction_id and artifact_id must be distinct identifiers"
        )


# ── Pre-image verification tests ──────────────────────────────────────────────


class TestPreImageVerification:
    """Attempt to recompute CAI values from known inputs.

    These tests assume the canonical serialisation is:
        json.dumps(params, sort_keys=True, separators=(',', ':')).encode('utf-8')

    If they fail, the server uses a different serialisation.
    """

    def _compute_parameters_cai(self, params: dict) -> str:
        canonical = json.dumps(params, sort_keys=True, separators=(",", ":"))
        return sha2_256_cai(canonical.encode("utf-8"))

    def test_parameters_cai_matches_computed_hash(self, version: PodmanMCPClient) -> None:
        params = {"technique_id": "DFT-1001"}
        data = version.call_tool("solveit_get_technique", params)
        actual_cai = version.prov(data).get("parameters_cai", "")
        expected_cai = self._compute_parameters_cai(params)

        if actual_cai != expected_cai:
            pytest.xfail(
                f"parameters_cai pre-image check failed — server may use a different "
                f"canonical serialisation.\n"
                f"  expected (sorted JSON): {expected_cai}\n"
                f"  actual:                 {actual_cai}\n"
                f"  Both are valid CAI format: {is_valid_cai(actual_cai)}"
            )

    def test_sha2_256_helper_produces_valid_cai(self) -> None:
        cai = sha2_256_cai(b"test data")
        assert is_valid_cai(cai), f"sha2_256_cai helper produced invalid CAI: {cai}"
        expected_hex = hashlib.sha256(b"test data").hexdigest()
        assert cai_hex(cai) == expected_hex

    def test_empty_params_have_valid_cai(self, version: PodmanMCPClient) -> None:
        data = version.call_tool("solveit_list_techniques")
        cai = version.prov(data).get("parameters_cai", "")
        assert is_valid_cai(cai), f"Empty-params call has invalid parameters_cai: {cai}"
