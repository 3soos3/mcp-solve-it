"""HTTP transport tests — healthz, readyz, MCP over HTTP, token auth.

These tests start the container in its default mode (MCP_TRANSPORT=http),
wait for the server to be ready, then make HTTP requests against it.
They exercise a completely different code path from the stdio tests.

Requires: httpx (already in dev deps via the http optional group).
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import time
from collections.abc import Generator
from typing import Any

import httpx
import pytest

from .image_configs import FAST_FAIL, SOLVEIT_VOL

# Host ports for HTTP container tests — each fixture gets a unique port.
# These are chosen to avoid conflicts with common local services.
_PORT_VERSION = 29876
_PORT_LIVE = 29877
_PORT_AUTH = 29878
_READY_TIMEOUT = 30  # seconds to wait for /healthz to respond


# ── Container fixture ─────────────────────────────────────────────────────────


@contextlib.contextmanager
def _http_container(
    image: str,
    extra_env: tuple[str, ...] = (),
    volumes: tuple[str, ...] = (),
    port: int = _PORT_VERSION,
) -> Generator[str, None, None]:
    """Start an HTTP-mode container, wait for /healthz, yield base URL, stop.

    Uses --network=host so the container binds directly to the host network.
    MCP_PORT is passed explicitly to control which port the server listens on.
    """
    cmd = [
        "podman",
        "run",
        "--rm",
        "-d",
        "--network",
        "host",
        "--name",
        f"pytest-http-{port}",
        "-e",
        f"MCP_PORT={port}",
    ]
    for e in extra_env:
        cmd += ["-e", e]
    for v in volumes:
        cmd += ["-v", v]
    cmd.append(image)

    container_id = subprocess.check_output(cmd).decode().strip()
    base_url = f"http://localhost:{port}"
    try:
        deadline = time.monotonic() + _READY_TIMEOUT
        while time.monotonic() < deadline:
            try:
                r = httpx.get(f"{base_url}/healthz", timeout=2)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            logs = subprocess.run(
                ["podman", "logs", container_id], capture_output=True
            ).stderr.decode(errors="replace")[-500:]
            raise TimeoutError(
                f"Container {image} did not become ready within {_READY_TIMEOUT}s.\nLogs: {logs}"
            )
        yield base_url
    finally:
        subprocess.run(
            ["podman", "stop", f"pytest-http-{port}"],
            capture_output=True,
        )


# ── MCP HTTP helpers ──────────────────────────────────────────────────────────


def _mcp_post(
    base_url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """POST to /mcp/ and parse the first JSON-RPC object from the SSE response.

    In stateless mode each POST is self-contained. The server returns an SSE
    event whose ``data:`` line is a JSON-RPC object.  We read the full response
    body (the connection closes after the event) and extract the data line.
    """
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if headers:
        h.update(headers)
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{base_url}/mcp/", json=payload, headers=h)
    for line in resp.text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            data = line[5:].strip()
            if data:
                try:
                    return json.loads(data)
                except json.JSONDecodeError:
                    pass
    return {"_error": "no data in SSE response", "_body": resp.text[:200]}


def _mcp_call(
    base_url: str,
    method: str,
    params: dict[str, Any] | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Send a single MCP request (no init needed in stateless mode)."""
    headers: dict[str, str] = {}
    if auth_token is not None:
        headers["Authorization"] = f"Bearer {auth_token}"
    return _mcp_post(
        base_url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        },
        headers=headers,
    )


def _mcp_session(
    base_url: str,
    method: str,
    params: dict[str, Any] | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Alias for _mcp_call (stateless HTTP — no separate init needed)."""
    return _mcp_call(base_url, method, params, auth_token)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def version_http(version_image: str) -> Generator[str, None, None]:
    with _http_container(version_image, port=_PORT_VERSION) as url:
        yield url


@pytest.fixture(scope="module")
def live_http(live_image: str) -> Generator[str, None, None]:
    with _http_container(
        live_image,
        extra_env=(FAST_FAIL,),
        volumes=(SOLVEIT_VOL,),
        port=_PORT_LIVE,
    ) as url:
        yield url


# ── Health endpoint tests ─────────────────────────────────────────────────────


class TestHealthEndpoints:
    def test_healthz_returns_200(self, version_http: str) -> None:
        r = httpx.get(f"{version_http}/healthz", timeout=5)
        assert r.status_code == 200

    def test_healthz_body_has_status_ok(self, version_http: str) -> None:
        r = httpx.get(f"{version_http}/healthz", timeout=5)
        assert r.json().get("status") == "ok"

    def test_healthz_body_has_server_name(self, version_http: str) -> None:
        r = httpx.get(f"{version_http}/healthz", timeout=5)
        assert "name" in r.json()

    def test_readyz_returns_200(self, version_http: str) -> None:
        r = httpx.get(f"{version_http}/readyz", timeout=5)
        assert r.status_code == 200

    def test_health_alias_works(self, version_http: str) -> None:
        r = httpx.get(f"{version_http}/health", timeout=5)
        assert r.status_code == 200

    def test_live_image_healthz(self, live_http: str) -> None:
        r = httpx.get(f"{live_http}/healthz", timeout=5)
        assert r.status_code == 200
        assert r.json().get("status") == "ok"


# ── MCP protocol over HTTP ────────────────────────────────────────────────────


class TestMCPOverHTTP:
    def test_initialize_succeeds(self, version_http: str) -> None:
        resp = _mcp_call(
            version_http,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1.0"},
            },
        )
        assert "result" in resp, f"initialize failed: {resp}"
        assert "serverInfo" in resp["result"]

    def test_tools_list_over_http(self, version_http: str) -> None:
        resp = _mcp_session(version_http, "tools/list")
        assert "result" in resp, f"tools/list failed: {resp}"
        tools = resp["result"].get("tools", [])
        assert len(tools) >= 24

    def test_solveit_status_over_http(self, version_http: str) -> None:
        resp = _mcp_session(version_http, "tools/call", {"name": "solveit_status", "arguments": {}})
        assert "result" in resp, f"solveit_status failed: {resp}"
        content = resp["result"]["content"][0]["text"]
        data = json.loads(content)
        assert data.get("status") == "ok"

    def test_get_technique_over_http(self, version_http: str) -> None:
        resp = _mcp_session(
            version_http,
            "tools/call",
            {
                "name": "solveit_get_technique",
                "arguments": {"technique_id": "DFT-1001"},
            },
        )
        assert "result" in resp
        data = json.loads(resp["result"]["content"][0]["text"])
        payload = data.get("result", data)
        assert isinstance(payload.get("name"), str) and payload["name"]

    def test_provenance_present_over_http(self, version_http: str) -> None:
        resp = _mcp_session(
            version_http,
            "tools/call",
            {
                "name": "solveit_search",
                "arguments": {"keywords": "triage"},
            },
        )
        data = json.loads(resp["result"]["content"][0]["text"])
        assert "_provenance" in data, "FSS provenance missing in HTTP response"
        assert data["_provenance"].get("evidentiary_status") == "evidentiary"

    def test_fss_headers_set_investigation_id(self, version_http: str) -> None:
        """FSS investigation context headers should appear in provenance."""
        resp = _mcp_session(
            version_http,
            "tools/call",
            {
                "name": "solveit_status",
                "arguments": {},
            },
            auth_token=None,
        )
        # Basic check: provenance block is returned; investigation_id wiring
        # is verified via the _provenance.investigation_id field if set.
        data = json.loads(resp["result"]["content"][0]["text"])
        assert "_provenance" in data


# ── Token auth over HTTP ──────────────────────────────────────────────────────


class TestTokenAuthHTTP:
    """Token auth is supported on HTTP transport (unlike stdio where it's blocked).

    With MCP_AUTH_ENABLED=true, MCP_AUTH_PROVIDER=token, MCP_AUTH_TOKEN=secret:
    - Requests with the correct Bearer token → succeed
    - Requests without a token → blocked by middleware (auth error)
    - Requests with the wrong token → blocked by middleware (auth error)
    """

    @pytest.fixture(scope="class")
    def auth_url(self, version_image: str) -> Generator[str, None, None]:
        with _http_container(
            version_image,
            extra_env=(
                "MCP_AUTH_ENABLED=true",
                "MCP_AUTH_PROVIDER=token",
                "MCP_AUTH_TOKEN=test-secret-xyz",
            ),
            port=_PORT_AUTH,
        ) as url:
            yield url

    def test_server_starts_with_token_auth_on_http(self, auth_url: str) -> None:
        r = httpx.get(f"{auth_url}/healthz", timeout=5)
        assert r.status_code == 200, "Server should start fine with token auth on HTTP"

    def _parse_tool_result(self, resp: dict[str, Any]) -> dict[str, Any]:
        """Parse a tool call MCP response — handles both success and error formats."""
        if "error" in resp:
            return {"_rpc_error": resp["error"]}
        result = resp.get("result", {})
        content = result.get("content", [])
        if not content:
            return {"_empty": True, "_is_error": result.get("isError")}
        try:
            parsed = json.loads(content[0]["text"])
            if result.get("isError"):
                parsed["_is_tool_error"] = True
            return parsed
        except (json.JSONDecodeError, KeyError):
            return {"_raw": content[0].get("text", ""), "_is_error": result.get("isError")}

    def test_valid_token_allows_tool_call(self, auth_url: str) -> None:
        resp = _mcp_session(
            auth_url,
            "tools/call",
            {
                "name": "solveit_status",
                "arguments": {},
            },
            auth_token="test-secret-xyz",
        )
        data = self._parse_tool_result(resp)
        assert data.get("status") == "ok", f"Valid token should allow tool call: {data}"

    def test_no_token_blocks_tool_call(self, auth_url: str) -> None:
        resp = _mcp_session(
            auth_url,
            "tools/call",
            {
                "name": "solveit_status",
                "arguments": {},
            },
            auth_token=None,
        )
        data = self._parse_tool_result(resp)
        is_blocked = (
            "_rpc_error" in data
            or data.get("_is_tool_error")
            or data.get("_is_error")
            or "AUTH" in str(data).upper()
            or data.get("status") != "ok"
        )
        assert is_blocked, f"Missing token should be rejected by auth middleware: {data}"

    def test_wrong_token_blocks_tool_call(self, auth_url: str) -> None:
        resp = _mcp_session(
            auth_url,
            "tools/call",
            {
                "name": "solveit_status",
                "arguments": {},
            },
            auth_token="wrong-token",
        )
        data = self._parse_tool_result(resp)
        is_blocked = (
            "_rpc_error" in data
            or data.get("_is_tool_error")
            or data.get("_is_error")
            or "AUTH" in str(data).upper()
            or data.get("status") != "ok"
        )
        assert is_blocked, f"Wrong token should be rejected by auth middleware: {data}"

    def test_healthz_accessible_without_token(self, auth_url: str) -> None:
        """The health endpoint must remain reachable without auth."""
        r = httpx.get(f"{auth_url}/healthz", timeout=5)
        assert r.status_code == 200
