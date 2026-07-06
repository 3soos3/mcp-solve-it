"""Container-level OTel tests — verifies telemetry init inside the live image.

These tests run against a real podman container.  They are the only tests that
can catch issues such as missing packages inside the image, wrong import paths
baked into a layer, or the SDK crashing at init time in the actual runtime
environment.

Each test spawns a fresh container, performs the full MCP handshake + one tool
call (which is what triggers the lazy OTel singleton), then inspects stderr.
"""

from __future__ import annotations

import json
import subprocess
import threading
from typing import Any

import pytest

from .image_configs import FAST_FAIL

_OTEL_ENABLED = "MCP_OTEL_ENABLED=true"
# Use an unreachable loopback address inside the container so the OTLP exporter
# fails silently on export — but init still completes and the log message appears.
_FAKE_ENDPOINT = "MCP_OTEL_ENDPOINT=http://127.0.0.1:14317"


def _readline_timeout(proc: subprocess.Popen[bytes], timeout: float) -> bytes | None:
    result: list[bytes | None] = [None]

    def _read() -> None:
        try:
            result[0] = proc.stdout.readline()  # type: ignore[union-attr]
        except Exception:
            pass

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(timeout)
    return result[0]


def _run_tool_capture_stderr(
    image: str,
    tool: str,
    extra_env: tuple[str, ...] = (),
    timeout: int = 45,
) -> tuple[dict[str, Any], str]:
    """Spawn a container, call one tool, return (parsed_response, stderr_text).

    Unlike PodmanMCPClient.call_tool this also captures stderr, which is where
    the OTel init log message appears.
    """
    cmd = ["podman", "run", "--rm", "-i", "-e", "MCP_TRANSPORT=stdio"]
    for e in extra_env:
        cmd += ["-e", e]
    cmd.append(image)

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    def send(obj: dict[str, Any]) -> None:
        try:
            proc.stdin.write(json.dumps(obj).encode() + b"\n")  # type: ignore[union-attr]
            proc.stdin.flush()  # type: ignore[union-attr]
        except BrokenPipeError:
            pass

    try:
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "otel-image-test", "version": "1.0"},
                },
            }
        )

        raw = _readline_timeout(proc, timeout=15)
        if not raw:
            proc.kill()
            stderr = proc.stderr.read(500).decode(errors="replace")  # type: ignore[union-attr]
            return {"_error": "no initialize response"}, stderr

        send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        send(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool, "arguments": {}},
            }
        )

        response: dict[str, Any] = {}
        for _ in range(40):
            raw = _readline_timeout(proc, timeout=float(timeout))
            if raw is None:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and obj.get("id") == 2:
                    response = obj
                    break
            except json.JSONDecodeError:
                pass

    except Exception as exc:
        try:
            proc.kill()
        except Exception:
            pass
        return {"_error": str(exc)}, ""

    # The OTel init message is written to stderr during KB load, well before the
    # tool response arrives — it is already in the pipe buffer.  Kill immediately
    # rather than waiting for gRPC retry timeouts (~15 s with an unreachable endpoint).
    proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.stdin.close()  # type: ignore[union-attr]
    except Exception:
        pass
    stderr = proc.stderr.read().decode(errors="replace")  # type: ignore[union-attr]

    if not response:
        return {"_error": "no id=2 response"}, stderr
    return response, stderr


@pytest.mark.slow
class TestOTelInContainer:
    """OTel behaviour verified against a running container."""

    def test_otel_init_logged_when_enabled(self, live_image: str) -> None:
        """MCP_OTEL_ENABLED=true must produce 'OpenTelemetry initialised' in stderr."""
        _, stderr = _run_tool_capture_stderr(
            live_image,
            "solveit_status",
            extra_env=(FAST_FAIL, _OTEL_ENABLED, _FAKE_ENDPOINT),
        )
        assert "OpenTelemetry initialised" in stderr, (
            f"Expected OTel init log in stderr.\nstderr was:\n{stderr}"
        )

    def test_server_responds_despite_unreachable_exporter(self, live_image: str) -> None:
        """An unreachable OTLP endpoint must not crash the server or drop the tool response."""
        resp, _ = _run_tool_capture_stderr(
            live_image,
            "solveit_status",
            extra_env=(FAST_FAIL, _OTEL_ENABLED, _FAKE_ENDPOINT),
        )
        assert "_error" not in resp, f"Server crashed or timed out with OTel enabled:\n{resp}"
        content = resp.get("result", {}).get("content", [])
        assert content, "Expected non-empty content in solveit_status response"

    def test_otel_not_initialised_when_disabled(self, live_image: str) -> None:
        """By default (MCP_OTEL_ENABLED unset) the OTel init message must not appear."""
        _, stderr = _run_tool_capture_stderr(
            live_image,
            "solveit_status",
            extra_env=(FAST_FAIL,),
        )
        assert "OpenTelemetry initialised" not in stderr, (
            f"OTel init must be silent when disabled.\nstderr was:\n{stderr}"
        )

    def test_otel_service_name_logged(self, live_image: str) -> None:
        """The init log must include the service name (default: mcp-solve-it)."""
        _, stderr = _run_tool_capture_stderr(
            live_image,
            "solveit_status",
            extra_env=(FAST_FAIL, _OTEL_ENABLED, _FAKE_ENDPOINT),
        )
        assert "mcp-solve-it" in stderr, (
            f"Expected default service name in OTel init log.\nstderr was:\n{stderr}"
        )

    def test_otel_custom_service_name_logged(self, live_image: str) -> None:
        """A custom MCP_OTEL_SERVICE_NAME must appear in the init log."""
        _, stderr = _run_tool_capture_stderr(
            live_image,
            "solveit_status",
            extra_env=(
                FAST_FAIL,
                _OTEL_ENABLED,
                _FAKE_ENDPOINT,
                "MCP_OTEL_SERVICE_NAME=my-forensic-server",
            ),
        )
        assert "my-forensic-server" in stderr, (
            f"Expected custom service name in OTel init log.\nstderr was:\n{stderr}"
        )

    def test_otel_endpoint_logged(self, live_image: str) -> None:
        """The configured endpoint must appear in the init log."""
        _, stderr = _run_tool_capture_stderr(
            live_image,
            "solveit_status",
            extra_env=(FAST_FAIL, _OTEL_ENABLED, _FAKE_ENDPOINT),
        )
        assert "127.0.0.1:14317" in stderr, (
            f"Expected endpoint in OTel init log.\nstderr was:\n{stderr}"
        )

    def test_otel_custom_environment_logged(self, live_image: str) -> None:
        """A custom MCP_OTEL_ENVIRONMENT must appear in the init log."""
        _, stderr = _run_tool_capture_stderr(
            live_image,
            "solveit_status",
            extra_env=(
                FAST_FAIL,
                _OTEL_ENABLED,
                _FAKE_ENDPOINT,
                "MCP_OTEL_ENVIRONMENT=ci-integration",
            ),
        )
        assert "ci-integration" in stderr, (
            f"Expected custom environment in OTel init log.\nstderr was:\n{stderr}"
        )
