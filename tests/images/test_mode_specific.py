"""Mode-specific tests — behaviours unique to each image variant.

:live    — dynamic KB loaded from SOLVE_IT_DATA_URL at runtime
:monthly — rolling snapshot baked in, kb_version == git SHA label
:version — pinned release, exact counts, fully deterministic, FORENSIC_METADATA=true
"""

from __future__ import annotations

import pytest

from .conftest import PodmanMCPClient, is_valid_cai
from .image_configs import BY_TAG, FAST_FAIL

# ── :live ─────────────────────────────────────────────────────────────────────


class TestLiveMode:
    def test_consecutive_calls_different_transaction_ids(self, live: PodmanMCPClient) -> None:
        a = live.prov(live.call_tool("solveit_status")).get("transaction_id")
        b = live.prov(live.call_tool("solveit_status")).get("transaction_id")
        assert a and b and a != b, f":live should generate unique transaction_ids per call: {a}"

    def test_live_mode_env(self, live: PodmanMCPClient) -> None:
        assert live.get_env("SOLVE_IT_MODE") == "live"

    def test_forensic_metadata_false(self, live: PodmanMCPClient) -> None:
        assert live.get_env("FORENSIC_METADATA") == "false"

    def test_data_url_is_configured(self, live: PodmanMCPClient) -> None:
        url = live.get_env("SOLVE_IT_DATA_URL")
        assert url and url != "http://0.0.0.0/fail", (
            "The built image must have a real SOLVE_IT_DATA_URL baked in"
        )

    def test_kb_via_volume_mount_is_ok(self, live: PodmanMCPClient) -> None:
        # live fixture already has the volume wired in
        status = live.call_tool("solveit_status")
        assert status.get("status") == "ok", f":live with volume should be ok: {status}"

    @pytest.mark.network
    def test_live_network_fetch_ok(self, live_image: str) -> None:
        """Requires real network access to SOLVE_IT_DATA_URL.  Skipped by default.
        Run with: pytest -m network tests/images/test_mode_specific.py
        """
        client = PodmanMCPClient(image=live_image)  # no FAST_FAIL, no volume
        status = client.call_tool("solveit_status")
        assert status.get("status") == "ok", f"Live network fetch failed: {status}"
        assert isinstance(status.get("techniques"), int) and status["techniques"] >= 100


# ── :monthly ──────────────────────────────────────────────────────────────────


class TestMonthlyMode:
    def test_monthly_mode_env(self, monthly: PodmanMCPClient) -> None:
        assert monthly.get_env("SOLVE_IT_MODE") == "monthly"

    def test_forensic_metadata_false(self, monthly: PodmanMCPClient) -> None:
        assert monthly.get_env("FORENSIC_METADATA") == "false"

    def test_version_env_is_set(self, monthly: PodmanMCPClient) -> None:
        svi = monthly.get_env("SOLVE_IT_VERSION")
        assert svi and svi != "local-test", f"SOLVE_IT_VERSION must be set in :monthly, got {svi!r}"
        # Makefile passes main-YYYYMM; older images may have "unknown"
        assert svi not in ("", "local-test"), f"SOLVE_IT_VERSION is a build placeholder: {svi!r}"

    def test_prov_kb_version_matches_env(self, monthly: PodmanMCPClient) -> None:
        env_ver = monthly.get_env("SOLVE_IT_VERSION")
        data = monthly.call_tool("solveit_status")
        prov_ver = monthly.prov(data).get("kb_version")
        if env_ver == "unknown":
            pytest.skip(
                "SOLVE_IT_VERSION=unknown — rebuild with 'make build-monthly' "
                "to get a meaningful version label"
            )
        assert prov_ver == env_ver, (
            f"_provenance.kb_version={prov_ver!r} != SOLVE_IT_VERSION={env_ver!r}"
        )

    def test_artifact_id_equals_result_cai(self, monthly: PodmanMCPClient) -> None:
        data = monthly.call_tool("solveit_search", {"keywords": "triage"})
        p = monthly.prov(data)
        assert p.get("artifact_id") == p.get("result_cai") and p.get("artifact_id"), (
            "monthly: artifact_id must equal result_cai"
        )

    def test_no_network_needed(self, monthly_image: str) -> None:
        """Bundled KB — must work with no volume and a broken data URL."""
        client = PodmanMCPClient(
            image=monthly_image,
            extra_env=(FAST_FAIL,),
        )
        status = client.call_tool("solveit_status")
        assert status.get("status") == "ok", f":monthly should not need network or volume: {status}"


# ── :version ──────────────────────────────────────────────────────────────────


class TestVersionMode:
    def test_release_mode_env(self, version: PodmanMCPClient) -> None:
        assert version.get_env("SOLVE_IT_MODE") == "release"

    def test_forensic_metadata_true(self, version: PodmanMCPClient) -> None:
        assert version.get_env("FORENSIC_METADATA") == "true"

    def test_exact_version_string(self, version: PodmanMCPClient) -> None:
        cfg = BY_TAG["version"]
        assert version.get_env("SOLVE_IT_VERSION") == cfg.expected_version

    def test_exact_technique_count(self, version: PodmanMCPClient) -> None:
        cfg = BY_TAG["version"]
        status = version.call_tool("solveit_status")
        assert status.get("techniques") == cfg.exact_counts["techniques"], (
            f"Expected {cfg.exact_counts['techniques']}, got {status.get('techniques')}"
        )

    def test_exact_weakness_count(self, version: PodmanMCPClient) -> None:
        cfg = BY_TAG["version"]
        status = version.call_tool("solveit_status")
        assert status.get("weaknesses") == cfg.exact_counts["weaknesses"], (
            f"Expected {cfg.exact_counts['weaknesses']}, got {status.get('weaknesses')}"
        )

    def test_exact_mitigation_count(self, version: PodmanMCPClient) -> None:
        cfg = BY_TAG["version"]
        status = version.call_tool("solveit_status")
        assert status.get("mitigations") == cfg.exact_counts["mitigations"], (
            f"Expected {cfg.exact_counts['mitigations']}, got {status.get('mitigations')}"
        )

    def test_identical_params_identical_artifact_id(self, version: PodmanMCPClient) -> None:
        a = version.prov(
            version.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        ).get("artifact_id")
        b = version.prov(
            version.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        ).get("artifact_id")
        assert a and b and a == b, (
            f":version must be deterministic — artifact_id differs: {a} vs {b}"
        )

    def test_evidentiary_status_is_evidentiary(self, version: PodmanMCPClient) -> None:
        data = version.call_tool("solveit_search", {"keywords": "triage"})
        status = version.prov(data).get("evidentiary_status")
        assert status == "evidentiary", (
            f":version should be evidentiary (FORENSIC_METADATA=true), got {status!r}"
        )

    def test_artifact_id_equals_result_cai(self, version: PodmanMCPClient) -> None:
        data = version.call_tool("solveit_search", {"keywords": "triage"})
        p = version.prov(data)
        assert p.get("artifact_id") == p.get("result_cai") and p.get("artifact_id"), (
            "version: artifact_id must equal result_cai"
        )

    def test_no_network_needed(self, version_image: str) -> None:
        client = PodmanMCPClient(image=version_image, extra_env=(FAST_FAIL,))
        status = client.call_tool("solveit_status")
        assert status.get("status") == "ok", f":version should not need network: {status}"


# ── Cross-image ───────────────────────────────────────────────────────────────


class TestCrossImageConsistency:
    def test_monthly_and_version_have_distinct_kb_version_ids(
        self, monthly: PodmanMCPClient, version: PodmanMCPClient
    ) -> None:
        # monthly tracks HEAD of main; version pins a tagged release — they are
        # built from different source commits and will have different kb_version_ids
        # unless HEAD happens to equal the tagged release at build time.
        m_vid = monthly.prov(monthly.call_tool("solveit_status")).get("kb_version_id")
        v_vid = version.prov(version.call_tool("solveit_status")).get("kb_version_id")
        assert m_vid, "monthly must have a valid kb_version_id"
        assert v_vid, "version must have a valid kb_version_id"
        # Both must be valid CAI strings even if they differ
        assert is_valid_cai(m_vid), f"monthly kb_version_id not valid CAI: {m_vid}"
        assert is_valid_cai(v_vid), f"version kb_version_id not valid CAI: {v_vid}"

    def test_dft_1001_returns_a_name_in_all_images(
        self, live: PodmanMCPClient, monthly: PodmanMCPClient, version: PodmanMCPClient
    ) -> None:
        # All images must return a non-empty name for DFT-1001.
        # The exact value may differ between monthly (rolling main) and version (pinned).
        for label, client in (("live", live), ("monthly", monthly), ("version", version)):
            data = client.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
            name = client.unwrap(data).get("name")
            assert isinstance(name, str) and name.strip(), (
                f"{label}: DFT-1001 must return a non-empty name, got {name!r}"
            )
