"""Environment variable configuration tests for all three image variants.

Verifies that each image is built with the expected compile-time env vars.
These checks run against the image itself (no MCP handshake needed) using
``podman run --entrypoint /bin/sh``.
"""

from __future__ import annotations

import pytest

from .conftest import PodmanMCPClient
from .image_configs import BY_TAG


class TestSolveItMode:
    @pytest.mark.parametrize(
        "fixture_name,expected",
        [
            ("live", "live"),
            ("monthly", "monthly"),
            ("version", "release"),
        ],
    )
    def test_solve_it_mode(
        self, fixture_name: str, expected: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        assert client.get_env("SOLVE_IT_MODE") == expected

    @pytest.mark.parametrize(
        "fixture_name,expected",
        [
            ("live", "false"),
            ("monthly", "false"),
            ("version", "true"),
        ],
    )
    def test_forensic_metadata(
        self, fixture_name: str, expected: str, request: pytest.FixtureRequest
    ) -> None:
        client: PodmanMCPClient = request.getfixturevalue(fixture_name)
        assert client.get_env("FSS_METADATA") == expected


class TestLiveEnv:
    def test_data_dir(self, live: PodmanMCPClient) -> None:
        assert live.get_env("SOLVE_IT_DATA_DIR") == "/tmp/app-cache/solve-it"

    def test_data_url_configured(self, live: PodmanMCPClient) -> None:
        assert bool(live.get_env("SOLVE_IT_DATA_URL"))


class TestMonthlyEnv:
    def test_version_is_set(self, monthly: PodmanMCPClient) -> None:
        # Monthly is a rolling build; SOLVE_IT_VERSION may be a SHA, "main", or "unknown"
        # when SOLVEIT_SHA/SOLVE_IT_VERSION is not explicitly passed at build time.
        # The meaningful check is that the env var exists (even if "unknown").
        svi = monthly.get_env("SOLVE_IT_VERSION")
        assert svi is not None, "SOLVE_IT_VERSION env var must be present"

    def test_data_path(self, monthly: PodmanMCPClient) -> None:
        assert monthly.get_env("MCP_APP_SOLVEIT_DATA_PATH") == "/app/solve-it-main"


class TestVersionEnv:
    def test_version_pinned(self, version: PodmanMCPClient) -> None:
        cfg = BY_TAG["version"]
        assert version.get_env("SOLVE_IT_VERSION") == cfg.expected_version

    def test_data_path(self, version: PodmanMCPClient) -> None:
        assert version.get_env("MCP_APP_SOLVEIT_DATA_PATH") == "/app/solve-it-main"
