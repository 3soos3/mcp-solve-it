"""Core KB tool tests — parametrised across all three image variants.

Every test in this module runs for :live (via volume mount), :monthly, and
:version.  The parametrised fixture ``any_client`` wires this up automatically.
"""

from __future__ import annotations

from .conftest import PodmanMCPClient
from .image_configs import BY_TAG


class TestStatus:
    def test_status_ok(self, any_client: PodmanMCPClient) -> None:
        status = any_client.call_tool("solveit_status")
        assert status.get("status") == "ok", str(status)[:120]

    def test_technique_count_meets_threshold(self, any_client: PodmanMCPClient) -> None:
        cfg = BY_TAG[any_client.config.tag]  # type: ignore[union-attr]
        status = any_client.call_tool("solveit_status")
        count = status.get("techniques", 0)
        assert isinstance(count, int) and count >= cfg.min_counts["techniques"], (
            f"techniques={count}, want ≥{cfg.min_counts['techniques']}"
        )

    def test_weakness_count_meets_threshold(self, any_client: PodmanMCPClient) -> None:
        cfg = BY_TAG[any_client.config.tag]  # type: ignore[union-attr]
        status = any_client.call_tool("solveit_status")
        count = status.get("weaknesses", 0)
        assert isinstance(count, int) and count >= cfg.min_counts["weaknesses"], (
            f"weaknesses={count}, want ≥{cfg.min_counts['weaknesses']}"
        )

    def test_mitigation_count_meets_threshold(self, any_client: PodmanMCPClient) -> None:
        cfg = BY_TAG[any_client.config.tag]  # type: ignore[union-attr]
        status = any_client.call_tool("solveit_status")
        count = status.get("mitigations", 0)
        assert isinstance(count, int) and count >= cfg.min_counts["mitigations"], (
            f"mitigations={count}, want ≥{cfg.min_counts['mitigations']}"
        )

    def test_citation_count_present(self, any_client: PodmanMCPClient) -> None:
        status = any_client.call_tool("solveit_status")
        assert "citations" in status or "citation_count" in status, (
            "solveit_status should include a citation count"
        )


class TestDatabaseDescription:
    def test_returns_database_name(self, any_client: PodmanMCPClient) -> None:
        data = any_client.call_tool("solveit_get_database_description")
        payload = any_client.unwrap(data)
        assert isinstance(payload, dict) and "database_name" in payload, (
            f"database_name missing: {payload}"
        )

    def test_returns_statistics(self, any_client: PodmanMCPClient) -> None:
        data = any_client.call_tool("solveit_get_database_description")
        payload = any_client.unwrap(data)
        assert "statistics" in payload, f"statistics missing: {list(payload.keys())}"


class TestSearch:
    def test_search_memory_returns_results(self, any_client: PodmanMCPClient) -> None:
        data = any_client.call_tool("solveit_search", {"keywords": "memory"})
        payload = any_client.unwrap(data)
        total = (
            len(payload.get("techniques", []))
            + len(payload.get("weaknesses", []))
            + len(payload.get("mitigations", []))
        )
        assert total > 0, "solveit_search('memory') returned no results"

    def test_search_acquisition_returns_techniques(self, any_client: PodmanMCPClient) -> None:
        data = any_client.call_tool("solveit_search", {"keywords": "acquisition"})
        payload = any_client.unwrap(data)
        assert len(payload.get("techniques", [])) > 0, (
            "solveit_search('acquisition') returned no techniques"
        )

    def test_search_result_structure(self, any_client: PodmanMCPClient) -> None:
        data = any_client.call_tool("solveit_search", {"keywords": "triage"})
        payload = any_client.unwrap(data)
        assert isinstance(payload, dict), f"Expected dict, got {type(payload)}"
        # All three result lists should be present (even if empty)
        for key in ("techniques", "weaknesses", "mitigations"):
            assert key in payload, f"Missing '{key}' in search response"


class TestGetTechnique:
    def test_dft_1001_returns_a_name(self, any_client: PodmanMCPClient) -> None:
        data = any_client.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        payload = any_client.unwrap(data)
        name = payload.get("name")
        assert isinstance(name, str) and name.strip(), (
            f"DFT-1001 must return a non-empty name, got {name!r}"
        )

    def test_dft_1001_name_is_triage_in_version(self, version: PodmanMCPClient) -> None:
        # The exact name is pinned to the v0.2026-06 release.
        # Rolling builds (monthly) may use a different name from the current main branch.
        data = version.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        payload = version.unwrap(data)
        assert payload.get("name") == "Triage", (
            f"DFT-1001 name expected 'Triage' in :version, got {payload.get('name')!r}"
        )

    def test_technique_has_description(self, any_client: PodmanMCPClient) -> None:
        data = any_client.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        payload = any_client.unwrap(data)
        assert isinstance(payload.get("description"), str) and payload["description"].strip()

    def test_technique_has_weaknesses_key(self, any_client: PodmanMCPClient) -> None:
        data = any_client.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        payload = any_client.unwrap(data)
        assert "weaknesses" in payload, (
            f"DFT-1001 response missing 'weaknesses': {list(payload.keys())}"
        )


class TestGetWeaknessesForTechnique:
    def test_dft_1001_weaknesses_non_empty(self, any_client: PodmanMCPClient) -> None:
        data = any_client.call_tool(
            "solveit_get_weaknesses_for_technique", {"technique_id": "DFT-1001"}
        )
        payload = any_client.unwrap(data)
        assert isinstance(payload, list) and len(payload) > 0, (
            f"Expected non-empty list for DFT-1001 weaknesses, got {payload}"
        )

    def test_weakness_entry_has_id(self, any_client: PodmanMCPClient) -> None:
        data = any_client.call_tool(
            "solveit_get_weaknesses_for_technique", {"technique_id": "DFT-1001"}
        )
        payload = any_client.unwrap(data)
        first = payload[0] if isinstance(payload, list) and payload else {}
        assert "id" in first or "weakness_id" in first, f"Weakness entry missing id field: {first}"


class TestListTechniques:
    def test_returns_at_least_100(self, any_client: PodmanMCPClient) -> None:
        data = any_client.call_tool("solveit_list_techniques")
        payload = any_client.unwrap(data)
        assert isinstance(payload, list) and len(payload) >= 100, (
            f"solveit_list_techniques returned {len(payload) if isinstance(payload, list) else 'n/a'}"  # noqa: E501
        )

    def test_count_consistent_with_status(self, any_client: PodmanMCPClient) -> None:
        status = any_client.call_tool("solveit_status")
        list_data = any_client.call_tool("solveit_list_techniques")
        status_count = status.get("techniques", -1)
        list_count = len(any_client.unwrap(list_data) or [])
        assert status_count == list_count, (
            f"Status reports {status_count} techniques but list returns {list_count}"
        )


class TestGetCitation:
    def test_dfcite_1001_returns_data(self, any_client: PodmanMCPClient) -> None:
        data = any_client.call_tool("solveit_get_citation", {"citation_id": "DFCite-1001"})
        payload = any_client.unwrap(data)
        assert isinstance(payload, dict) and "error" not in payload, (
            f"solveit_get_citation DFCite-1001 unexpected: {payload}"
        )

    def test_citation_has_bibtex_or_reference(self, any_client: PodmanMCPClient) -> None:
        data = any_client.call_tool("solveit_get_citation", {"citation_id": "DFCite-1001"})
        payload = any_client.unwrap(data)
        has_ref = "bibtex" in payload or "reference" in payload or "url" in payload
        assert has_ref, f"Citation response has no reference fields: {list(payload.keys())}"


class TestObjectivesForTechnique:
    def test_dft_1001_objectives_non_empty(self, any_client: PodmanMCPClient) -> None:
        data = any_client.call_tool(
            "solveit_get_objectives_for_technique", {"technique_id": "DFT-1001"}
        )
        payload = any_client.unwrap(data)
        assert isinstance(payload, list) and len(payload) > 0, (
            f"Expected objectives for DFT-1001, got {payload}"
        )


class TestResolveCitations:
    def test_processes_text_without_markers(self, any_client: PodmanMCPClient) -> None:
        data = any_client.call_tool(
            "solveit_resolve_inline_citations",
            {"text": "No citation markers here."},
        )
        payload = any_client.unwrap(data)
        assert "resolved_text" in payload, f"Missing resolved_text: {payload}"

    def test_resolves_actual_citation_marker(self, any_client: PodmanMCPClient) -> None:
        data = any_client.call_tool(
            "solveit_resolve_inline_citations",
            {"text": "See [DFCite-1001] for details."},
        )
        payload = any_client.unwrap(data)
        resolved = payload.get("resolved_text", "")
        # The marker must be transformed — bracket form [DFCite-1001] must be gone
        assert "[DFCite-1001]" not in resolved, (
            f"Citation marker was not processed in resolved_text: {resolved!r}"
        )
