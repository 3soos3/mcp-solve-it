"""Tool registration and schema tests across all three image variants.

Covers:
- Tool count with a loaded KB
- Required MCP fields on every tool
- FSS schema annotations (x-fss-tool-version, x-fss-idempotent) on :version
- Health check always present
- Known KB tool names present when KB is loaded
"""

from __future__ import annotations

import pytest

from .conftest import PodmanMCPClient

_KNOWN_KB_TOOLS = {
    "solveit_status",
    "solveit_get_database_description",
    "solveit_search",
    "solveit_get_technique",
    "solveit_get_weakness",
    "solveit_get_mitigation",
    "solveit_list_techniques",
    "solveit_list_weaknesses",
    "solveit_list_mitigations",
    "solveit_list_objectives",
    "solveit_get_techniques_for_objective",
    "solveit_get_weaknesses_for_technique",
    "solveit_get_mitigations_for_weakness",
    "solveit_get_techniques_for_weakness",
    "solveit_get_weaknesses_for_mitigation",
    "solveit_get_techniques_for_mitigation",
    "solveit_get_mitigations_for_technique",
    "solveit_get_objectives_for_technique",
    "solveit_list_available_mappings",
    "solveit_load_objective_mapping",
    "solveit_list_loaded_extensions",
    "solveit_get_citation",
    "solveit_list_citations",
    "solveit_resolve_inline_citations",
}


class TestToolCount:
    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_at_least_24_tools(self, fixture_name: str, request: pytest.FixtureRequest) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        names = client.tool_names()
        assert len(names) >= 24, f"{fixture_name} exposed only {len(names)} tools: {names}"


class TestToolSchema:
    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_all_tools_have_required_mcp_fields(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        tools = client.list_tools()
        for tool in tools:
            assert "name" in tool, f"Tool missing 'name': {tool}"
            assert "description" in tool, f"Tool {tool.get('name')} missing 'description'"
            assert "inputSchema" in tool, f"Tool {tool.get('name')} missing 'inputSchema'"
            assert isinstance(tool["description"], str) and tool["description"].strip(), (
                f"Tool {tool.get('name')} has empty description"
            )


class TestHealthCheck:
    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_health_check_registered(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        assert "__health_check" in client.tool_names()

    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_health_check_callable(self, fixture_name: str, request: pytest.FixtureRequest) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        result = client.call_tool("__health_check")
        assert "_error" not in result
        assert "server_name" in result
        assert "uptime_seconds" in result
        assert "tools_loaded" in result


class TestKnownKBTools:
    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_known_kb_tools_present(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        names = client.tool_names()
        missing = _KNOWN_KB_TOOLS - names
        assert not missing, f"{fixture_name} is missing expected tools: {sorted(missing)}"


class TestFSSSchemaAnnotations:
    """FSS tool schema extensions — only verified on :version (FSS_METADATA=true)."""

    @pytest.fixture(scope="class")
    def version_tools(self, version: PodmanMCPClient) -> dict[str, dict]:
        return {t["name"]: t for t in version.list_tools()}

    def test_get_technique_fss_tool_version(self, version_tools: dict[str, dict]) -> None:
        schema = version_tools["solveit_get_technique"].get("inputSchema", {})
        assert schema.get("x-fss-tool-version") == "1.0.0", (
            f"x-fss-tool-version not set: {schema.get('x-fss-tool-version')}"
        )

    def test_get_technique_fss_idempotent(self, version_tools: dict[str, dict]) -> None:
        schema = version_tools["solveit_get_technique"].get("inputSchema", {})
        assert schema.get("x-fss-idempotent") is True

    def test_multiple_tools_have_fss_annotations(self, version_tools: dict[str, dict]) -> None:
        annotated = [
            name
            for name, tool in version_tools.items()
            if tool.get("inputSchema", {}).get("x-fss-tool-version")
        ]
        assert len(annotated) >= 3, f"Expected ≥3 tools with x-fss-tool-version, got {annotated}"
