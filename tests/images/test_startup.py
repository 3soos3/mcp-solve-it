"""Container startup and degraded-mode tests.

Degraded mode is triggered by setting both:
  SOLVE_IT_DATA_URL=http://0.0.0.0/fail  (unreachable URL)
  MCP_APP_INIT_REQUIRED=false            (allow startup despite KB load failure)

In degraded mode the server starts but reports status=error and exposes only
the two baseline tools (__health_check and solveit_status).
"""

from __future__ import annotations

import pytest

from .conftest import PodmanMCPClient
from .image_configs import DEGRADED, FAST_FAIL, SOLVEIT_VOL


class TestDegradedMode:
    """The :live image tested in degraded mode (bad URL + init not required)."""

    @pytest.fixture(scope="class")
    def degraded(self, live_image: str) -> PodmanMCPClient:
        return PodmanMCPClient(
            image=live_image,
            extra_env=(FAST_FAIL, DEGRADED),
        )

    def test_container_starts_without_crash(self, degraded: PodmanMCPClient) -> None:
        status = degraded.call_tool("solveit_status")
        assert "_error" not in status, f"Container crashed in degraded mode: {status}"

    def test_status_returns_error(self, degraded: PodmanMCPClient) -> None:
        status = degraded.call_tool("solveit_status")
        assert status.get("status") == "error"

    def test_error_message_present(self, degraded: PodmanMCPClient) -> None:
        status = degraded.call_tool("solveit_status")
        assert status.get("error") or status.get("message"), \
            "Expected an error explanation in degraded solveit_status"

    def test_only_baseline_tools_exposed(self, degraded: PodmanMCPClient) -> None:
        names = degraded.tool_names()
        assert "__health_check" in names
        assert "solveit_status" in names
        assert "solveit_get_technique" not in names, \
            "KB tools must be absent when KB failed to load"

    def test_tool_count_is_exactly_two(self, degraded: PodmanMCPClient) -> None:
        names = degraded.tool_names()
        assert len(names) == 2, f"Expected exactly 2 tools in degraded mode, got {names}"

    def test_health_check_still_works(self, degraded: PodmanMCPClient) -> None:
        result = degraded.call_tool("__health_check")
        assert "_error" not in result
        assert "server_name" in result


class TestFastFail:
    """The :live image with a bad data URL but without degraded mode override —
    init is required, so the container should surface the failure in status."""

    @pytest.fixture(scope="class")
    def fast_fail(self, live_image: str) -> PodmanMCPClient:
        # FAST_FAIL only — no DEGRADED, so default init behaviour applies
        return PodmanMCPClient(image=live_image, extra_env=(FAST_FAIL,))

    def test_status_not_ok_without_kb(self, fast_fail: PodmanMCPClient) -> None:
        status = fast_fail.call_tool("solveit_status")
        # Either error or a transport error — either way not "ok"
        assert status.get("status") != "ok"

    def test_mounted_kb_overrides_fast_fail(self, live_image: str) -> None:
        """Mounting the KB volume makes status ok even with FAST_FAIL."""
        client = PodmanMCPClient(
            image=live_image,
            volumes=(SOLVEIT_VOL,),
            extra_env=(FAST_FAIL,),
        )
        status = client.call_tool("solveit_status")
        assert status.get("status") == "ok", f"Expected ok with mounted KB: {status}"


class TestBundledImages:
    """Monthly and version images must start and serve the KB without any volume."""

    @pytest.mark.parametrize("fixture_name", ["monthly", "version"])
    def test_bundled_image_starts_ok(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        status = client.call_tool("solveit_status")
        assert status.get("status") == "ok", \
            f"{fixture_name} should start ok without volume: {status}"
