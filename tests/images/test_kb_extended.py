"""Extended KB tool tests — tools not covered by the original 75-test script.

Runs on :monthly and :version only (bundled KB images, ``bundled_client``
fixture).  Tests for tools whose names aren't 100% certain are prefixed
with a ``tool_exists`` check and skip gracefully if absent.
"""

from __future__ import annotations

import pytest

from .conftest import PodmanMCPClient


def _require_tool(client: PodmanMCPClient, name: str) -> None:
    """Skip the test if the tool is not in tools/list."""
    if name not in client.tool_names():
        pytest.skip(f"tool {name!r} not present in this image")


class TestMitigationsForWeakness:
    def test_dfw_1002_mitigations_non_empty(self, bundled_client: PodmanMCPClient) -> None:
        data = bundled_client.call_tool(
            "solveit_get_mitigations_for_weakness", {"weakness_id": "DFW-1002"}
        )
        payload = bundled_client.unwrap(data)
        assert isinstance(payload, list) and len(payload) > 0, (
            f"Expected mitigations for DFW-1002, got {payload}"
        )


class TestMitigationsForTechnique:
    def test_dft_1001_mitigations_non_empty(self, bundled_client: PodmanMCPClient) -> None:
        data = bundled_client.call_tool(
            "solveit_get_mitigations_for_technique", {"technique_id": "DFT-1001"}
        )
        payload = bundled_client.unwrap(data)
        count = (
            len(payload.get("mitigations", []))
            if isinstance(payload, dict)
            else len(payload)
            if isinstance(payload, list)
            else 0
        )
        assert count > 0, f"Expected mitigations for DFT-1001, got {payload}"


class TestGetWeakness:
    def test_dfw_1001_returns_name(self, bundled_client: PodmanMCPClient) -> None:
        data = bundled_client.call_tool("solveit_get_weakness", {"weakness_id": "DFW-1001"})
        payload = bundled_client.unwrap(data)
        assert isinstance(payload.get("name"), str) and len(payload["name"]) > 5, (
            f"DFW-1001 name unexpected: {payload.get('name')!r}"
        )

    def test_weakness_id_not_used_as_name(self, bundled_client: PodmanMCPClient) -> None:
        data = bundled_client.call_tool("solveit_get_weakness", {"weakness_id": "DFW-1001"})
        payload = bundled_client.unwrap(data)
        assert "DFW-1001" not in payload.get("name", ""), (
            "Weakness name should not be the ID itself"
        )


class TestGetMitigation:
    def test_dfm_1001_returns_name(self, bundled_client: PodmanMCPClient) -> None:
        data = bundled_client.call_tool("solveit_get_mitigation", {"mitigation_id": "DFM-1001"})
        payload = bundled_client.unwrap(data)
        assert isinstance(payload, dict) and "name" in payload, f"DFM-1001 missing name: {payload}"


class TestListWeaknesses:
    def test_returns_non_empty_list(self, bundled_client: PodmanMCPClient) -> None:
        _require_tool(bundled_client, "solveit_list_weaknesses")
        data = bundled_client.call_tool("solveit_list_weaknesses")
        payload = bundled_client.unwrap(data)
        assert isinstance(payload, list) and len(payload) >= 100, (
            f"Expected ≥100 weaknesses, got {len(payload) if isinstance(payload, list) else payload}"  # noqa: E501
        )

    def test_count_consistent_with_status(self, bundled_client: PodmanMCPClient) -> None:
        _require_tool(bundled_client, "solveit_list_weaknesses")
        status = bundled_client.call_tool("solveit_status")
        list_data = bundled_client.call_tool("solveit_list_weaknesses")
        status_count = status.get("weaknesses", -1)
        list_count = len(bundled_client.unwrap(list_data) or [])
        assert status_count == list_count, (
            f"Status reports {status_count} weaknesses but list returns {list_count}"
        )


class TestListMitigations:
    def test_returns_non_empty_list(self, bundled_client: PodmanMCPClient) -> None:
        _require_tool(bundled_client, "solveit_list_mitigations")
        data = bundled_client.call_tool("solveit_list_mitigations")
        payload = bundled_client.unwrap(data)
        assert isinstance(payload, list) and len(payload) >= 100, (
            f"Expected ≥100 mitigations, got {len(payload) if isinstance(payload, list) else payload}"  # noqa: E501
        )

    def test_count_consistent_with_status(self, bundled_client: PodmanMCPClient) -> None:
        _require_tool(bundled_client, "solveit_list_mitigations")
        status = bundled_client.call_tool("solveit_status")
        list_data = bundled_client.call_tool("solveit_list_mitigations")
        status_count = status.get("mitigations", -1)
        list_count = len(bundled_client.unwrap(list_data) or [])
        assert status_count == list_count, (
            f"Status reports {status_count} mitigations but list returns {list_count}"
        )


class TestTechniquesForWeakness:
    def test_dfw_1001_techniques_non_empty(self, bundled_client: PodmanMCPClient) -> None:
        _require_tool(bundled_client, "solveit_get_techniques_for_weakness")
        data = bundled_client.call_tool(
            "solveit_get_techniques_for_weakness", {"weakness_id": "DFW-1001"}
        )
        payload = bundled_client.unwrap(data)
        assert isinstance(payload, list) and len(payload) > 0, (
            f"Expected techniques for DFW-1001, got {payload}"
        )

    def test_reverse_relationship_consistent(self, bundled_client: PodmanMCPClient) -> None:
        """DFW-1001 should appear in DFT-1001's weaknesses, and DFT-1001 should appear
        in DFW-1001's techniques — if the reverse lookup tool exists."""
        _require_tool(bundled_client, "solveit_get_techniques_for_weakness")
        techs_for_weak = bundled_client.unwrap(
            bundled_client.call_tool(
                "solveit_get_techniques_for_weakness", {"weakness_id": "DFW-1001"}
            )
        )
        ids = [
            e.get("id") or e.get("technique_id")
            for e in (techs_for_weak if isinstance(techs_for_weak, list) else [])
        ]
        assert "DFT-1001" in ids, f"DFT-1001 not found in reverse lookup for DFW-1001: {ids[:5]}"


class TestTechniquesForMitigation:
    def test_dfm_1001_techniques_non_empty(self, bundled_client: PodmanMCPClient) -> None:
        _require_tool(bundled_client, "solveit_get_techniques_for_mitigation")
        data = bundled_client.call_tool(
            "solveit_get_techniques_for_mitigation", {"mitigation_id": "DFM-1001"}
        )
        payload = bundled_client.unwrap(data)
        assert isinstance(payload, list) and len(payload) > 0, (
            f"Expected techniques for DFM-1001, got {payload}"
        )


class TestAvailableMappings:
    def test_includes_solve_it_json(self, bundled_client: PodmanMCPClient) -> None:
        data = bundled_client.call_tool("solveit_list_available_mappings")
        payload = bundled_client.unwrap(data)
        assert isinstance(payload, list), f"Expected list, got {type(payload)}"
        assert any("solve-it" in str(m) for m in payload), (
            f"solve-it.json not found in mappings: {payload}"
        )

    def test_get_mapping_returns_data(self, bundled_client: PodmanMCPClient) -> None:
        _require_tool(bundled_client, "solveit_get_mapping")
        data = bundled_client.call_tool("solveit_get_mapping", {"mapping_name": "solve-it.json"})
        payload = bundled_client.unwrap(data)
        assert isinstance(payload, (dict, list)) and payload, (
            f"solveit_get_mapping returned empty/unexpected: {payload}"
        )

    def test_load_objective_mapping_returns_data(self, bundled_client: PodmanMCPClient) -> None:
        _require_tool(bundled_client, "solveit_load_objective_mapping")
        data = bundled_client.call_tool(
            "solveit_load_objective_mapping", {"mapping_name": "solve-it.json"}
        )
        payload = bundled_client.unwrap(data)
        assert isinstance(payload, (dict, list)) and payload, (
            f"solveit_load_objective_mapping returned empty/unexpected: {payload}"
        )


class TestCitations:
    def test_list_citations_non_empty(self, bundled_client: PodmanMCPClient) -> None:
        _require_tool(bundled_client, "solveit_list_citations")
        data = bundled_client.call_tool("solveit_list_citations")
        payload = bundled_client.unwrap(data)
        assert isinstance(payload, list) and len(payload) > 0, (
            f"Expected non-empty citation list, got {payload}"
        )

    def test_citation_count_consistent_with_status(self, bundled_client: PodmanMCPClient) -> None:
        _require_tool(bundled_client, "solveit_list_citations")
        status = bundled_client.call_tool("solveit_status")
        list_data = bundled_client.call_tool("solveit_list_citations")
        status_count = status.get("citations", -1)
        list_count = len(bundled_client.unwrap(list_data) or [])
        assert status_count == list_count, (
            f"Status reports {status_count} citations but list returns {list_count}"
        )


class TestExtensions:
    def test_list_loaded_extensions_returns_data(self, bundled_client: PodmanMCPClient) -> None:
        _require_tool(bundled_client, "solveit_list_loaded_extensions")
        data = bundled_client.call_tool("solveit_list_loaded_extensions")
        payload = bundled_client.unwrap(data)
        # May return an empty list if no extensions are loaded, or a list of extension names
        assert isinstance(payload, list), (
            f"Expected a list from solveit_list_loaded_extensions, got {type(payload)}"
        )

    def test_extensions_enabled_in_status(self, bundled_client: PodmanMCPClient) -> None:
        # enable_extensions=true means extension techniques are included in the count.
        # Just verify status returns a technique count that reflects this.
        status = bundled_client.call_tool("solveit_status")
        assert isinstance(status.get("techniques"), int) and status["techniques"] > 0, (
            "Expected technique count with extensions enabled"
        )


@pytest.mark.slow
class TestSmokeAllTools:
    """Call every registered tool with minimal args and verify no container crash."""

    _MINIMAL_ARGS: dict[str, dict] = {
        "solveit_get_technique": {"technique_id": "DFT-1001"},
        "solveit_get_weakness": {"weakness_id": "DFW-1001"},
        "solveit_get_mitigation": {"mitigation_id": "DFM-1001"},
        "solveit_get_citation": {"citation_id": "DFCite-1001"},
        "solveit_get_weaknesses_for_technique": {"technique_id": "DFT-1001"},
        "solveit_get_mitigations_for_technique": {"technique_id": "DFT-1001"},
        "solveit_get_mitigations_for_weakness": {"weakness_id": "DFW-1002"},
        "solveit_get_objectives_for_technique": {"technique_id": "DFT-1001"},
        "solveit_get_techniques_for_weakness": {"weakness_id": "DFW-1001"},
        "solveit_get_techniques_for_mitigation": {"mitigation_id": "DFM-1001"},
        "solveit_search": {"keywords": "triage"},
        "solveit_resolve_inline_citations": {"text": "Test [DFCite-1001] text"},
        "solveit_get_mapping": {"mapping_name": "solve-it.json"},
        "solveit_load_objective_mapping": {"mapping_name": "solve-it.json"},
        "solveit_list_citations": {},
        "solveit_list_loaded_extensions": {},
        "__health_check": {},
        "solveit_status": {},
        "solveit_get_database_description": {},
        "solveit_list_techniques": {},
        "solveit_list_available_mappings": {},
    }

    def test_all_tools_respond_without_crash(self, bundled_client: PodmanMCPClient) -> None:
        tools = bundled_client.list_tools()
        errors: list[str] = []

        for tool in tools:
            name = tool["name"]
            args = self._MINIMAL_ARGS.get(name, {})
            result = bundled_client.call_tool(name, args)
            if "_error" in result and "parse failed" not in result["_error"]:
                errors.append(f"{name}: {result['_error']}")

        assert not errors, "Tools had transport/crash errors:\n" + "\n".join(errors)
