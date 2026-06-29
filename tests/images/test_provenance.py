"""FSS provenance (_provenance block) tests — parametrised across all variants.

The _provenance block attached to every tool response is the core of the
Forensic Science Standard (FSS) integration.  These tests verify its
structure and per-image semantics without verifying the hash values
themselves (that is test_cryptography.py's job).
"""

from __future__ import annotations

import pytest

from .conftest import PodmanMCPClient, is_valid_cai, is_valid_iso_utc, is_valid_uuid4


@pytest.fixture(scope="module")
def live_search(live: PodmanMCPClient) -> dict:
    return live.call_tool("solveit_search", {"keywords": "memory"})


@pytest.fixture(scope="module")
def monthly_search(monthly: PodmanMCPClient) -> dict:
    return monthly.call_tool("solveit_search", {"keywords": "acquisition"})


@pytest.fixture(scope="module")
def version_tech(version: PodmanMCPClient) -> dict:
    return version.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})


class TestProvenancePresent:
    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_provenance_block_present(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_search", {"keywords": "triage"})
        p = client.prov(data)
        assert p, f"{fixture_name}: _provenance block missing or empty"

    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_required_provenance_fields(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_search", {"keywords": "triage"})
        p = client.prov(data)
        for field in (
            "transaction_id",
            "tool_name",
            "tool_version",
            "kb_version_id",
            "evidentiary_status",
            "timestamp_utc",
            "artifact_id",
            "result_cai",
            "parameters_cai",
            "result_status",
        ):
            assert field in p, f"{fixture_name}: _provenance missing field '{field}'"


class TestTransactionId:
    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_transaction_id_is_uuid4(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_search", {"keywords": "triage"})
        tid = client.prov(data).get("transaction_id", "")
        assert is_valid_uuid4(tid), f"{fixture_name}: invalid UUID v4 transaction_id: {tid}"

    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_consecutive_calls_different_transaction_ids(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        a = client.prov(client.call_tool("solveit_status")).get("transaction_id")
        b = client.prov(client.call_tool("solveit_status")).get("transaction_id")
        assert a and b and a != b, f"{fixture_name}: same transaction_id across two calls: {a}"


class TestEvidentiaryStatus:
    def test_live_is_non_evidentiary(self, live_search: dict, live: PodmanMCPClient) -> None:
        assert live.prov(live_search).get("evidentiary_status") == "non-evidentiary"

    def test_monthly_is_non_evidentiary(
        self, monthly_search: dict, monthly: PodmanMCPClient
    ) -> None:
        assert monthly.prov(monthly_search).get("evidentiary_status") == "non-evidentiary"

    def test_version_is_evidentiary(self, version_tech: dict, version: PodmanMCPClient) -> None:
        assert version.prov(version_tech).get("evidentiary_status") == "evidentiary"


class TestCAIFields:
    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_parameters_cai_format(self, fixture_name: str, request: pytest.FixtureRequest) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_search", {"keywords": "triage"})
        cai = client.prov(data).get("parameters_cai", "")
        assert is_valid_cai(cai), f"{fixture_name}: invalid parameters_cai: {cai}"

    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_artifact_id_format(self, fixture_name: str, request: pytest.FixtureRequest) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_search", {"keywords": "triage"})
        cai = client.prov(data).get("artifact_id", "")
        assert is_valid_cai(cai), f"{fixture_name}: invalid artifact_id: {cai}"

    @pytest.mark.parametrize("fixture_name", ["monthly", "version"])
    def test_artifact_id_equals_result_cai(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_search", {"keywords": "triage"})
        p = client.prov(data)
        assert p.get("artifact_id") == p.get("result_cai") and p.get("artifact_id"), (
            f"{fixture_name}: artifact_id != result_cai: {p.get('artifact_id')!r}"
        )

    @pytest.mark.parametrize("fixture_name", ["monthly", "version"])
    def test_kb_version_id_format(self, fixture_name: str, request: pytest.FixtureRequest) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_status")
        cai = client.prov(data).get("kb_version_id", "")
        assert is_valid_cai(cai), f"{fixture_name}: invalid kb_version_id: {cai}"


class TestTimestamp:
    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_timestamp_is_iso_utc(self, fixture_name: str, request: pytest.FixtureRequest) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_search", {"keywords": "triage"})
        ts = client.prov(data).get("timestamp_utc", "")
        assert is_valid_iso_utc(ts), f"{fixture_name}: invalid timestamp_utc: {ts!r}"

    def test_version_timestamp_ends_with_z(
        self, version_tech: dict, version: PodmanMCPClient
    ) -> None:
        ts = version.prov(version_tech).get("timestamp_utc", "")
        assert str(ts).endswith("Z") or str(ts).endswith("+00:00"), (
            f"FSS-0005 requires UTC timestamp; got {ts!r}"
        )


class TestKBVersionConsistency:
    def test_monthly_kb_version_matches_env(self, monthly: PodmanMCPClient) -> None:
        env_ver = monthly.get_env("SOLVE_IT_VERSION")
        data = monthly.call_tool("solveit_status")
        prov_ver = monthly.prov(data).get("kb_version")
        if env_ver == "unknown":
            pytest.skip("SOLVE_IT_VERSION=unknown — rebuild with make build-monthly")
        assert prov_ver == env_ver, f"prov.kb_version={prov_ver!r} != SOLVE_IT_VERSION={env_ver!r}"

    def test_different_tools_same_kb_version_id(self, version: PodmanMCPClient) -> None:
        a = version.prov(version.call_tool("solveit_status")).get("kb_version_id")
        b = version.prov(
            version.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        ).get("kb_version_id")
        assert a and b and a == b, "kb_version_id should be stable within the same image"

    def test_monthly_and_version_both_have_valid_kb_version_ids(
        self, monthly: PodmanMCPClient, version: PodmanMCPClient
    ) -> None:
        # monthly (HEAD of main) and version (tagged release) are built from
        # different source commits — their kb_version_ids will differ.
        # This test only verifies both are valid CAI strings.
        m_vid = monthly.prov(monthly.call_tool("solveit_status")).get("kb_version_id")
        v_vid = version.prov(version.call_tool("solveit_status")).get("kb_version_id")
        assert is_valid_cai(m_vid), f"monthly kb_version_id invalid: {m_vid}"
        assert is_valid_cai(v_vid), f"version kb_version_id invalid: {v_vid}"


class TestDifferentParamsDifferentCAI:
    def test_different_params_produce_different_parameters_cai(
        self, version: PodmanMCPClient
    ) -> None:
        a = version.prov(version.call_tool("solveit_search", {"keywords": "memory"})).get(
            "parameters_cai"
        )
        b = version.prov(version.call_tool("solveit_search", {"keywords": "acquisition"})).get(
            "parameters_cai"
        )
        assert a and b and a != b, "Different parameters should produce different parameters_cai"
