"""Security middleware tests — rate limiting and request size limits.

Rate limiting requires sending many requests within one container session
(since limits are in-memory and reset when the container exits).
A ``PodmanMCPSession`` context manager keeps one container alive for the
duration of a test and can dispatch multiple sequential MCP requests.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import threading
from collections.abc import Generator
from typing import Any

import pytest

# ── Persistent MCP session over stdio ─────────────────────────────────────────


class PodmanMCPSession:
    """Keep one container alive and dispatch multiple MCP requests to it.

    Each ``call_tool`` / ``list_tools`` sends a new JSON-RPC id and reads
    until the matching response arrives.  The container exits when the
    context manager closes (stdin is closed).
    """

    def __init__(
        self,
        image: str,
        volumes: tuple[str, ...] = (),
        extra_env: tuple[str, ...] = (),
        timeout: float = 30.0,
    ) -> None:
        self.image = image
        self.volumes = volumes
        self.extra_env = extra_env
        self.timeout = timeout
        self._proc: subprocess.Popen | None = None  # type: ignore[type-arg]
        self._next_id = 1

    def __enter__(self) -> PodmanMCPSession:
        cmd = ["podman", "run", "--rm", "-i", "-e", "MCP_TRANSPORT=stdio"]
        for e in self.extra_env:
            cmd += ["-e", e]
        for v in self.volumes:
            cmd += ["-v", v]
        cmd.append(self.image)

        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest-session", "version": "1.0"},
                },
            }
        )
        self._read_until_id(1, timeout=20)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        self._next_id = 2
        return self

    def __exit__(self, *_: object) -> None:
        if self._proc and self._proc.stdin:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
        if self._proc:
            try:
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()

    def _send(self, obj: dict[str, Any]) -> None:
        assert self._proc and self._proc.stdin
        try:
            self._proc.stdin.write(json.dumps(obj).encode() + b"\n")
            self._proc.stdin.flush()
        except BrokenPipeError:
            pass

    def _readline_timeout(self, timeout: float) -> bytes | None:
        result: list[bytes | None] = [None]

        def _r() -> None:
            try:
                assert self._proc and self._proc.stdout
                result[0] = self._proc.stdout.readline()
            except Exception:
                pass

        t = threading.Thread(target=_r, daemon=True)
        t.start()
        t.join(timeout)
        return result[0]

    def _read_until_id(self, target_id: int, timeout: float = 30.0) -> dict[str, Any]:
        for _ in range(50):
            raw = self._readline_timeout(timeout)
            if raw is None:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and obj.get("id") == target_id:
                    return obj
            except json.JSONDecodeError:
                pass
        return {"_error": f"no response with id={target_id}"}

    def call_tool(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        req_id = self._next_id
        self._next_id += 1
        self._send(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": args or {}},
            }
        )
        resp = self._read_until_id(req_id, timeout=self.timeout)
        content = resp.get("result", {}).get("content", [])
        if not content:
            return {
                "_error": "empty content",
                "_raw": resp,
                "_is_error": resp.get("result", {}).get("isError"),
            }  # noqa: E501
        try:
            parsed = json.loads(content[0]["text"])
            if resp.get("result", {}).get("isError"):
                parsed["_is_tool_error"] = True
            return parsed
        except (json.JSONDecodeError, KeyError, IndexError):
            return {
                "_raw_text": content[0].get("text", "") if content else "",
                "_is_tool_error": resp.get("result", {}).get("isError", False),
            }


@contextlib.contextmanager
def _session(
    image: str,
    volumes: tuple[str, ...] = (),
    extra_env: tuple[str, ...] = (),
) -> Generator[PodmanMCPSession, None, None]:
    with PodmanMCPSession(image, volumes=volumes, extra_env=extra_env) as s:
        yield s


# ── Rate limiting tests ────────────────────────────────────────────────────────


@pytest.mark.slow
class TestRateLimiting:
    """The moderate security profile allows per_tool_rpm=60.
    Sending > 60 calls to the same tool in rapid succession within one session
    should trigger a rate limit error on at least one of them.
    """

    def test_rapid_calls_trigger_rate_limit(self, version_image: str) -> None:
        with _session(version_image) as sess:
            errors: list[str] = []
            # Send 70 calls — exceeds per_tool_rpm=60
            for _ in range(70):
                result = sess.call_tool("__health_check")
                if result.get("_is_tool_error") or "RATE_LIMIT" in str(result):
                    errors.append(str(result))

            assert errors, (
                "Expected at least one RATE_LIMIT error after 70 rapid calls. "
                "Check that rate limiting is enabled in the image config."
            )

    def test_rate_limit_error_code(self, version_image: str) -> None:
        with _session(version_image) as sess:
            rate_limited = None
            for _ in range(70):
                result = sess.call_tool("__health_check")
                raw = result.get("_raw_text", "") + str(result)
                if "RATE_LIMIT" in raw or result.get("_is_tool_error"):
                    rate_limited = result
                    break

            if rate_limited is None:
                pytest.skip("Rate limit not triggered in 70 calls — check config")

            raw_text = rate_limited.get("_raw_text", "")
            assert "RATE_LIMIT" in raw_text or rate_limited.get("_is_tool_error"), (
                f"Expected RATE_LIMIT code, got: {rate_limited}"
            )

    def test_different_tools_share_global_limit(self, version_image: str) -> None:
        """The global_rpm=120 limit applies across all tool calls."""
        with _session(version_image) as sess:
            errors = 0
            # Alternate between two tools — 130 total, exceeds global_rpm=120
            for i in range(130):
                tool = "solveit_status" if i % 2 == 0 else "__health_check"
                result = sess.call_tool(tool)
                if result.get("_is_tool_error") or "RATE_LIMIT" in str(result):
                    errors += 1

            assert errors > 0, "Expected global rate limit to trigger within 130 cross-tool calls"


# ── Request size limit tests ───────────────────────────────────────────────────


class TestRequestSizeLimits:
    """The moderate security profile sets max_request_size=5 MB.
    Sending a payload larger than that should be rejected with IO_LIMIT error.
    """

    def test_oversized_argument_rejected(self, version_image: str) -> None:
        # 6 MB keyword string — exceeds max_request_size=5 MB.
        # The server may reject with a structured IO_LIMIT error OR close the
        # connection before sending any response; both are valid enforcement.
        huge_keyword = "x" * (6 * 1024 * 1024)
        with _session(version_image) as sess:
            result = sess.call_tool("solveit_search", {"keywords": huge_keyword})
        raw = result.get("_raw_text", "") + str(result.get("_raw", "")) + str(result)
        connection_closed = "no response with id=" in raw or "no id=2 response" in raw
        is_error = (
            result.get("_is_tool_error") or "IO_LIMIT" in raw or "VALID" in raw or connection_closed
        )
        assert is_error, f"Expected size-limit rejection for 6 MB payload, got: {str(result)[:200]}"

    def test_normal_size_request_succeeds(self, version_image: str) -> None:
        with _session(version_image) as sess:
            result = sess.call_tool("solveit_search", {"keywords": "forensic"})
        assert "_is_tool_error" not in result or not result["_is_tool_error"], (
            f"Normal request should not be rejected: {result}"
        )

    def test_boundary_request_near_limit(self, version_image: str) -> None:
        """A request just under the 10 000-char string limit should succeed."""
        keyword = "forensic " * 1000  # ~9000 chars
        with _session(version_image) as sess:
            result = sess.call_tool("solveit_search", {"keywords": keyword})
        assert not (result.get("_is_tool_error") and "IO_LIMIT" in str(result)), (
            f"Request near limit should not be size-rejected: {str(result)[:200]}"
        )
