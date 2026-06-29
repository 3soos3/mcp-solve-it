"""Shared infrastructure for image-level tests.

PodmanMCPClient: synchronous MCP-over-stdio client that spawns a fresh
``podman run`` container per call. This matches the stateless approach of
test_images_75.py but integrates with pytest for proper test reporting,
filtering, and reruns.

Build the images before running these tests:
    make build-all          # build all three variants
    pytest tests/images/    # run the suite
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
from typing import Any

import pytest

from .image_configs import LIVE, MONTHLY, VERSION, ImageConfig

# ── Regex helpers ─────────────────────────────────────────────────────────────

UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
CAI_RE = re.compile(r"^sha2-256:[0-9a-f]{64}$")
ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$")


# ── pytest hooks ─────────────────────────────────────────────────────────────

def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--live-image",    default="solve-it-mcp:live",
                     help="Podman image tag for the :live variant")
    parser.addoption("--monthly-image", default="solve-it-mcp:monthly",
                     help="Podman image tag for the :monthly variant")
    parser.addoption("--version-image", default="solve-it-mcp:version",
                     help="Podman image tag for the :version variant")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers",
        "network: requires live network access to SOLVE_IT_DATA_URL")
    config.addinivalue_line("markers",
        "slow: test spawns multiple containers or is otherwise slow")
    config.addinivalue_line("markers",
        "auth: authentication and token behaviour tests")
    config.addinivalue_line("markers",
        "crypto: cryptographic hash verification tests")


# ── Image existence check ─────────────────────────────────────────────────────

def _image_exists(tag: str) -> bool:
    r = subprocess.run(["podman", "image", "exists", tag], capture_output=True)
    return r.returncode == 0


# ── PodmanMCPClient ───────────────────────────────────────────────────────────

class PodmanMCPClient:
    """Synchronous MCP client that spawns one ``podman run`` container per call.

    Each public method starts a fresh container, completes the MCP initialize
    handshake, sends the request, reads the response, and exits.  State from
    one call cannot bleed into the next — safe for concurrent pytest workers.

    Args:
        image:      Podman image to run.
        config:     The ImageConfig this client was created from (for assertions).
        volumes:    Volume mounts passed to ``podman run -v``.
        extra_env:  Extra ``-e KEY=VALUE`` strings passed to ``podman run``.
        timeout:    Per-readline timeout in seconds when reading MCP responses.
    """

    def __init__(
        self,
        image: str,
        config: ImageConfig | None = None,
        volumes: tuple[str, ...] = (),
        extra_env: tuple[str, ...] = (),
        timeout: int = 45,
    ) -> None:
        self.image = image
        self.config = config
        self.volumes = volumes
        self.extra_env = extra_env
        self.timeout = timeout

    # ── env inspection ────────────────────────────────────────────────────────

    def get_env(self, var: str) -> str:
        """Read an environment variable baked into the image."""
        r = subprocess.run(
            ["podman", "run", "--rm", "--entrypoint", "/bin/sh",
             self.image, "-c", f'echo "${var}"'],
            capture_output=True, timeout=15,
        )
        return r.stdout.decode().strip()

    # ── MCP transport primitives ──────────────────────────────────────────────

    @staticmethod
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

    def _build_cmd(
        self,
        extra_volumes: tuple[str, ...] = (),
        extra_env: tuple[str, ...] = (),
    ) -> list[str]:
        cmd = ["podman", "run", "--rm", "-i", "-e", "MCP_TRANSPORT=stdio"]
        for e in self.extra_env + extra_env:
            cmd += ["-e", e]
        for v in self.volumes + extra_volumes:
            cmd += ["-v", v]
        cmd.append(self.image)
        return cmd

    def _run_mcp(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        extra_volumes: tuple[str, ...] = (),
        extra_env: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Spawn a container, run one MCP request, return the raw JSON-RPC response."""
        cmd = self._build_cmd(extra_volumes, extra_env)
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        def _send(obj: dict[str, Any]) -> None:
            try:
                proc.stdin.write(json.dumps(obj).encode() + b"\n")  # type: ignore[union-attr]
                proc.stdin.flush()  # type: ignore[union-attr]
            except BrokenPipeError:
                pass

        try:
            _send({
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest-image-test", "version": "1.0"},
                },
            })

            raw = self._readline_timeout(proc, timeout=15)
            if not raw:
                stderr = proc.stderr.read(500).decode(errors="replace")  # type: ignore[union-attr]
                proc.wait(timeout=5)
                return {"_error": "no initialize response", "_stderr": stderr}

            _send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
            _send({"jsonrpc": "2.0", "id": 2, "method": method, "params": params or {}})

            for _ in range(40):
                raw = self._readline_timeout(proc, timeout=float(self.timeout))
                if raw is None:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict) and obj.get("id") == 2:
                        proc.stdin.close()  # type: ignore[union-attr]
                        proc.wait(timeout=5)
                        return obj
                except json.JSONDecodeError:
                    pass

            proc.stdin.close()  # type: ignore[union-attr]
            proc.wait(timeout=5)
            stderr = proc.stderr.read(500).decode(errors="replace")  # type: ignore[union-attr]
            return {"_error": "no id=2 response", "_stderr": stderr}

        except Exception as exc:
            try:
                proc.kill()
            except Exception:
                pass
            return {"_error": str(exc)}

    # ── Public API ────────────────────────────────────────────────────────────

    def list_tools(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Return the tools/list result."""
        resp = self._run_mcp("tools/list", **kwargs)
        return resp.get("result", {}).get("tools", [])

    def tool_names(self, **kwargs: Any) -> set[str]:
        return {t["name"] for t in self.list_tools(**kwargs)}

    def call_tool(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call a tool and return the parsed content dict.

        On success the dict may contain ``_provenance`` and ``result`` keys.
        On failure ``_error`` is set (key always present for errors).
        """
        resp = self._run_mcp(
            "tools/call", {"name": name, "arguments": args or {}}, **kwargs
        )
        result_block = resp.get("result", {})
        content = result_block.get("content", [])
        if not content:
            return {"_error": "empty content", "_raw": resp}
        text = content[0].get("text", "")
        try:
            parsed = json.loads(text)
            # Attach isError so tests can distinguish tool errors from transport errors
            if result_block.get("isError"):
                parsed["_is_tool_error"] = True
            return parsed
        except (json.JSONDecodeError, AttributeError):
            return {
                "_error": "parse failed",
                "_raw_text": text,
                "_is_tool_error": result_block.get("isError", False),
            }

    def container_stderr_on_start(
        self,
        extra_env: tuple[str, ...] = (),
        extra_volumes: tuple[str, ...] = (),
    ) -> tuple[int, str]:
        """Start the container, close stdin immediately, return (exit_code, stderr).

        Useful for testing startup failures (e.g. bad auth config).
        """
        cmd = self._build_cmd(extra_volumes, extra_env)
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        proc.stdin.close()  # type: ignore[union-attr]
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return -1, ""
        stderr = proc.stderr.read(2000).decode(errors="replace")  # type: ignore[union-attr]
        return proc.returncode, stderr

    # ── Provenance / payload helpers ──────────────────────────────────────────

    @staticmethod
    def prov(data: dict[str, Any]) -> dict[str, Any]:
        """Extract the _provenance block from a call_tool response."""
        return data.get("_provenance", {}) if isinstance(data, dict) else {}

    @staticmethod
    def unwrap(data: dict[str, Any]) -> Any:
        """Return the main payload, stripping _provenance and unwrapping 'result'."""
        if not isinstance(data, dict):
            return data
        if "result" in data and "_provenance" in data:
            return data["result"]
        return {k: v for k, v in data.items()
                if k not in ("_provenance", "_is_tool_error")}

    @staticmethod
    def is_tool_not_found(data: dict[str, Any]) -> bool:
        text = data.get("_raw_text", "")
        return "TOOL_NOT_FOUND" in text or "Unknown tool" in text


# ── CAI / UUID helpers (importable by tests) ──────────────────────────────────

def is_valid_cai(value: object) -> bool:
    """Validate sha2-256 CAI format: 'sha2-256:' + exactly 64 lowercase hex chars."""
    return bool(CAI_RE.match(str(value)))


def cai_hex(value: object) -> str:
    """Extract the hex digest portion from a CAI string."""
    s = str(value)
    return s.split(":", 1)[-1] if ":" in s else ""


def sha2_256_cai(data: bytes) -> str:
    """Compute the sha2-256 CAI string for the given bytes."""
    return "sha2-256:" + hashlib.sha256(data).hexdigest()


def is_valid_uuid4(value: object) -> bool:
    return bool(UUID_V4_RE.match(str(value)))


def is_valid_iso_utc(value: object) -> bool:
    return bool(ISO_UTC_RE.match(str(value)))


# ── Session-scoped image fixtures ─────────────────────────────────────────────

@pytest.fixture(scope="session")
def live_image(request: pytest.FixtureRequest) -> str:
    tag = request.config.getoption("--live-image", default="solve-it-mcp:live")
    if not _image_exists(tag):
        pytest.skip(f"image {tag!r} not found — run: make build-live")
    return tag  # type: ignore[return-value]


@pytest.fixture(scope="session")
def monthly_image(request: pytest.FixtureRequest) -> str:
    tag = request.config.getoption("--monthly-image", default="solve-it-mcp:monthly")
    if not _image_exists(tag):
        pytest.skip(f"image {tag!r} not found — run: make build-monthly")
    return tag  # type: ignore[return-value]


@pytest.fixture(scope="session")
def version_image(request: pytest.FixtureRequest) -> str:
    tag = request.config.getoption("--version-image", default="solve-it-mcp:version")
    if not _image_exists(tag):
        pytest.skip(f"image {tag!r} not found — run: make build-version")
    return tag  # type: ignore[return-value]


@pytest.fixture(scope="session")
def live(live_image: str) -> PodmanMCPClient:
    return PodmanMCPClient(
        image=live_image,
        config=LIVE,
        volumes=LIVE.default_volumes,
        extra_env=LIVE.default_extra_env,
    )


@pytest.fixture(scope="session")
def monthly(monthly_image: str) -> PodmanMCPClient:
    return PodmanMCPClient(image=monthly_image, config=MONTHLY)


@pytest.fixture(scope="session")
def version(version_image: str) -> PodmanMCPClient:
    return PodmanMCPClient(image=version_image, config=VERSION)


# ── Parametrised multi-image fixtures ────────────────────────────────────────

@pytest.fixture(params=["live", "monthly", "version"])
def any_client(request: pytest.FixtureRequest) -> PodmanMCPClient:
    """Parametrised fixture that runs each test for all three image variants."""
    return request.getfixturevalue(request.param)  # type: ignore[return-value]


@pytest.fixture(params=["monthly", "version"])
def bundled_client(request: pytest.FixtureRequest) -> PodmanMCPClient:
    """Parametrised fixture for images that have the KB baked in (no volume needed)."""
    return request.getfixturevalue(request.param)  # type: ignore[return-value]
