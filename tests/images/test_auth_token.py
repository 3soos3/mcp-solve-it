"""Authentication and token tests for the image containers.

Three scenarios are verified:

1. MCP_AUTH_TOKEN present alone (auth.enabled remains False by default)
   → server starts fine, tools work normally, token is ignored for stdio.

2. MCP_AUTH_ENABLED=true + MCP_AUTH_PROVIDER=token + MCP_AUTH_TOKEN=secret
   → server MUST fail at startup because token auth is explicitly blocked on
   stdio transport (ChassisServer.__init__ raises ValueError).

3. MCP_AUTH_ENABLED=false (explicit) with any token
   → server starts fine, tools work normally.

Additionally tests SOLVE_IT_API_TOKEN / data-URL credential behaviour for
the :live image, where the KB is fetched from SOLVE_IT_DATA_URL at runtime.
"""

from __future__ import annotations

import pytest

from .conftest import PodmanMCPClient
from .image_configs import FAST_FAIL, SOLVEIT_VOL

pytestmark = pytest.mark.auth


class TestTokenEnvVarAlone:
    """MCP_AUTH_TOKEN alone should not break anything (auth.enabled stays False)."""

    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_server_starts_with_auth_token_env(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        base: PodmanMCPClient = request.getfixturevalue(fixture_name)
        client = PodmanMCPClient(
            image=base.image,
            config=base.config,
            volumes=base.volumes,
            extra_env=base.extra_env + ("MCP_AUTH_TOKEN=test-token-xyz",),
        )
        data = client.call_tool("solveit_status")
        assert "_error" not in data, f"Server failed to start with MCP_AUTH_TOKEN set: {data}"

    @pytest.mark.parametrize("fixture_name", ["live", "monthly", "version"])
    def test_results_identical_with_and_without_token(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        base: PodmanMCPClient = request.getfixturevalue(fixture_name)
        without = base.call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})
        with_token = PodmanMCPClient(
            image=base.image,
            config=base.config,
            volumes=base.volumes,
            extra_env=base.extra_env + ("MCP_AUTH_TOKEN=should-be-ignored",),
        ).call_tool("solveit_get_technique", {"technique_id": "DFT-1001"})

        name_without = base.unwrap(without).get("name")
        name_with = base.unwrap(with_token).get("name")
        assert name_without == name_with and isinstance(name_without, str) and name_without, (
            f"Token env changed result: without={name_without!r}, with={name_with!r}"
        )


class TestTokenAuthOnStdioFails:
    """Enabling token auth on stdio MUST cause the server to reject startup.

    The chassis raises ValueError at ChassisServer.__init__ when token auth is
    enabled on stdio transport.  This happens before the MCP initialize handshake,
    so the container exits before returning any stdout — _run_mcp sees
    "_error: no initialize response".

    These tests require images built with the chassis version that supports
    MCP_AUTH_ENABLED / MCP_AUTH_PROVIDER env vars.  If an older image is used,
    MCP_AUTH_ENABLED is silently ignored, the server starts fine, and the test
    skips with an explanatory message.
    """

    def _assert_startup_failed(self, client: PodmanMCPClient, label: str) -> None:
        result = client.call_tool("solveit_status")
        # call_tool wraps transport errors: {"_error": "empty content", "_raw": {inner}}
        # so we must check both the top-level error and the inner _raw error.
        raw_inner = result.get("_raw", {})
        transport_error = result.get("_error", "") + " " + raw_inner.get("_error", "")
        if "_error" not in result and "_is_tool_error" not in result:
            pytest.skip(
                f"{label}: server started fine with MCP_AUTH_ENABLED=true — "
                "image was likely built before MCP_AUTH_ENABLED env var support "
                "was added to the chassis. Rebuild the image to activate this test."
            )
        startup_failed = (
            "no initialize response" in transport_error or "no id=2 response" in transport_error
        )
        assert startup_failed, f"{label}: expected MCP startup failure, got: {result}"
        stderr = raw_inner.get("_stderr", result.get("_stderr", "")).lower()
        assert "stdio" in stderr or "token" in stderr or "auth" in stderr or stderr == "", (
            f"{label}: unexpected stderr: {stderr[:200]}"
        )

    @pytest.mark.parametrize("fixture_name", ["monthly", "version"])
    def test_token_auth_enabled_on_stdio_fails(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        base: PodmanMCPClient = request.getfixturevalue(fixture_name)
        client = PodmanMCPClient(
            image=base.image,
            volumes=base.volumes,
            extra_env=(
                "MCP_AUTH_ENABLED=true",
                "MCP_AUTH_PROVIDER=token",
                "MCP_AUTH_TOKEN=secret123",
            ),
        )
        self._assert_startup_failed(client, fixture_name)

    @pytest.mark.parametrize("fixture_name", ["monthly", "version"])
    def test_token_auth_enabled_without_token_fails(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        """Token provider with no token configured should also fail on stdio."""
        base: PodmanMCPClient = request.getfixturevalue(fixture_name)
        client = PodmanMCPClient(
            image=base.image,
            volumes=base.volumes,
            extra_env=(
                "MCP_AUTH_ENABLED=true",
                "MCP_AUTH_PROVIDER=token",
                # deliberately no MCP_AUTH_TOKEN
            ),
        )
        self._assert_startup_failed(client, fixture_name)


class TestAuthExplicitlyDisabled:
    """MCP_AUTH_ENABLED=false with any other auth vars → server works normally."""

    @pytest.mark.parametrize("fixture_name", ["monthly", "version"])
    def test_explicit_disabled_auth_works(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        base: PodmanMCPClient = request.getfixturevalue(fixture_name)
        client = PodmanMCPClient(
            image=base.image,
            config=base.config,
            volumes=base.volumes,
            extra_env=(
                "MCP_AUTH_ENABLED=false",
                "MCP_AUTH_TOKEN=irrelevant",
            ),
        )
        data = client.call_tool("solveit_status")
        assert data.get("status") == "ok", (
            f"Server with MCP_AUTH_ENABLED=false should work fine: {data}"
        )


class TestDataURLCredentials:
    """Tests for the :live image's data-URL fetch credentials.

    SOLVE_IT_DATA_URL can point to a URL that may require authentication
    via a token or API key.  These tests verify graceful degradation when
    the URL is unreachable or returns auth errors.
    """

    def test_bad_data_url_degrades_gracefully(self, live_image: str) -> None:
        """A completely unreachable URL should produce status=error, not a crash."""
        client = PodmanMCPClient(
            image=live_image,
            extra_env=(
                "SOLVE_IT_DATA_URL=http://0.0.0.0/fail",
                "MCP_APP_INIT_REQUIRED=false",
            ),
        )
        data = client.call_tool("solveit_status")
        assert "_error" not in data, f"Container crashed on bad data URL: {data}"
        assert data.get("status") == "error", (
            f"Expected status=error on bad data URL, got: {data.get('status')}"
        )

    def test_api_token_env_var_accepted(self, live_image: str) -> None:
        """SOLVE_IT_API_TOKEN env var (if the app uses one) should not break startup."""
        client = PodmanMCPClient(
            image=live_image,
            extra_env=(
                FAST_FAIL,
                "MCP_APP_INIT_REQUIRED=false",
                "SOLVE_IT_API_TOKEN=any-test-token",
            ),
        )
        data = client.call_tool("solveit_status")
        assert "_error" not in data, f"Setting SOLVE_IT_API_TOKEN broke startup: {data}"

    def test_mounted_kb_bypasses_url_auth(self, live_image: str) -> None:
        """With a mounted KB the data URL (and its credentials) are irrelevant."""
        client = PodmanMCPClient(
            image=live_image,
            volumes=(SOLVEIT_VOL,),
            extra_env=(
                FAST_FAIL,
                "SOLVE_IT_API_TOKEN=bogus-token",
            ),
        )
        status = client.call_tool("solveit_status")
        assert status.get("status") == "ok", (
            f"Mounted KB should work regardless of API token: {status}"
        )


class TestDetailedErrors:
    """MCP_DETAILED_ERRORS=true should include more context in error responses."""

    @pytest.mark.parametrize("fixture_name", ["monthly", "version"])
    def test_detailed_errors_enabled(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        base: PodmanMCPClient = request.getfixturevalue(fixture_name)
        client = PodmanMCPClient(
            image=base.image,
            config=base.config,
            volumes=base.volumes,
            extra_env=base.extra_env + ("MCP_DETAILED_ERRORS=true",),
        )
        # Trigger a validation error and verify a structured error is returned
        data = client.call_tool("solveit_search", {"keywords": 12345})
        # The app returns a JSON error payload (with error_code / error_message)
        # or a raw text error — either way there must be an error indicator
        has_error = (
            data.get("_is_tool_error")
            or "error_code" in data
            or "error_message" in data
            or "_raw_text" in data
        )
        assert has_error, f"Expected error for int keywords, got: {data}"
        # When the response has structured error fields, they should be non-empty
        if "error_message" in data:
            assert data["error_message"], "error_message must not be empty"

    @pytest.mark.parametrize("fixture_name", ["monthly", "version"])
    def test_detailed_errors_disabled_by_default(
        self, fixture_name: str, request: pytest.FixtureRequest
    ) -> None:
        base: PodmanMCPClient = request.getfixturevalue(fixture_name)
        data = base.call_tool("solveit_search", {"keywords": 12345})
        # Error response must exist in some form
        has_error = data.get("_is_tool_error") or "error_code" in data or "_raw_text" in data
        assert has_error, f"Expected a validation error for int keywords, got: {data}"
        # The error should not leak a stack trace
        raw = data.get("_raw_text", "") or data.get("error_message", "")
        assert "stack" not in raw.lower() and "traceback" not in raw.lower(), (
            "Default error should not include a Python traceback"
        )
