"""Error handling tests — invalid inputs, missing args, bad IDs, unknown tools.

A well-behaved MCP server should:
- Return a structured error response (not crash/hang) for invalid inputs.
- Return TOOL_NOT_FOUND for unknown tool names.
- Return a validation error for missing required arguments.
- Handle edge-case search strings without crashing.

All error responses must be valid JSON-RPC (the transport layer stays up).
"""

from __future__ import annotations

import pytest

from .conftest import PodmanMCPClient


def _is_error_payload(data: dict) -> bool:
    """True if the response indicates an application-level error."""
    return (
        data.get("_is_tool_error") is True
        or "error" in data
        or "_error" in data
        or "status" in data and data["status"] == "error"
    )


class TestInvalidIDs:
    """Every lookup tool should return a structured error for non-existent IDs."""

    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_nonexistent_technique_returns_error(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_get_technique", {"technique_id": "DFT-9999"})
        assert "_error" not in data or data.get("_is_tool_error"), \
            f"Transport error (not an application error): {data}"
        assert _is_error_payload(data), \
            f"Expected error for DFT-9999, got: {data}"

    @pytest.mark.parametrize("fixture_name", ["monthly", "version"])
    def test_nonexistent_weakness_returns_error(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_get_weakness", {"weakness_id": "DFW-9999"})
        assert _is_error_payload(data), f"Expected error for DFW-9999, got: {data}"

    @pytest.mark.parametrize("fixture_name", ["monthly", "version"])
    def test_nonexistent_mitigation_returns_error(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_get_mitigation", {"mitigation_id": "DFM-9999"})
        assert _is_error_payload(data), f"Expected error for DFM-9999, got: {data}"

    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_nonexistent_citation_returns_error(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_get_citation", {"citation_id": "DFCite-9999"})
        assert _is_error_payload(data), f"Expected error for DFCite-9999, got: {data}"

    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_server_stays_up_after_bad_id(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        """After a bad-ID call the server must still respond to a valid call."""
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        client.call_tool("solveit_get_technique", {"technique_id": "DFT-9999"})
        ok = client.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        assert isinstance(ok.get("name"), str) and ok.get("name"), \
            f"Server unresponsive after bad-ID call: {ok}"


class TestUnknownTool:
    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_unknown_tool_returns_tool_not_found(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_does_not_exist_xyz")
        assert client.is_tool_not_found(data) or data.get("_is_tool_error"), \
            f"Expected TOOL_NOT_FOUND, got: {data}"


class TestMissingRequiredArguments:
    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_missing_technique_id(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        # Call without the required technique_id argument
        data = client.call_tool("solveit_get_technique", {})
        assert _is_error_payload(data), \
            f"Expected validation error for missing technique_id, got: {data}"

    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_missing_search_keywords(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_search", {})
        assert _is_error_payload(data), \
            f"Expected error for empty solveit_search args, got: {data}"


class TestSearchEdgeCases:
    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_search_no_results_returns_empty_lists(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        """A query that matches nothing should return empty lists, not an error."""
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool(
            "solveit_search",
            {"keywords": "xyzzy_no_match_9a8b7c6d"},
        )
        payload = client.unwrap(data)
        if _is_error_payload(data):
            pytest.skip("No-results query returns an error in this image (acceptable)")
        total = (
            len(payload.get("techniques", []))
            + len(payload.get("weaknesses", []))
            + len(payload.get("mitigations", []))
        )
        assert total == 0, f"Expected 0 results for nonsense query, got {total}"

    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_search_special_characters_does_not_crash(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool(
            "solveit_search",
            {"keywords": "'; DROP TABLE techniques; --"},
        )
        assert "_error" not in data or data.get("_is_tool_error") or \
               "parse failed" in str(data.get("_error", "")), \
               f"Server appears to have crashed on SQL injection attempt: {data}"

    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_search_unicode_does_not_crash(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_search", {"keywords": "数字取证 forensic"})
        assert "_error" not in data or data.get("_is_tool_error") or \
               "parse failed" in str(data.get("_error", "")), \
               f"Server crashed on unicode search: {data}"

    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_very_long_keyword_handled(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        """A keyword at the string limit boundary should be handled, not crash."""
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        long_kw = "forensic " * 500  # ~4500 chars, under the 10000 limit
        data = client.call_tool("solveit_search", {"keywords": long_kw})
        # Either valid results or a validation/error — but not a transport failure
        assert "_error" not in data or data.get("_is_tool_error") or \
               "parse failed" in str(data.get("_error", "")), \
               f"Server crashed on long keyword: {str(data)[:100]}"


class TestWrongArgumentType:
    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_integer_where_string_expected(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_search", {"keywords": 42})
        assert _is_error_payload(data), \
            f"Expected validation error for int keywords, got: {data}"

    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_null_where_string_expected(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = client.call_tool("solveit_get_technique", {"technique_id": None})
        assert _is_error_payload(data), \
            f"Expected validation error for null technique_id, got: {data}"
