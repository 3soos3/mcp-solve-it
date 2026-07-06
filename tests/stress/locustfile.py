"""
Stress test for fss-mcp-solve-it HTTP server (SOLVE-IT MCP).

Tests three scenarios:
  1. Health probes  — /healthz and /readyz (no MCP overhead)
  2. MCP light      — tools/list (cheapest MCP call)
  3. MCP heavy      — tools/call with solveit_search + solveit_get_technique

Rate limit note: server default is 100 RPM per client (MCP_RATE_LIMIT env var).
For class/NAT scenarios bump MCP_RATE_LIMIT or run with --users below the cap.

Run (server must be up on localhost:8000):
    locust -f tests/stress/locustfile.py --headless \\
        --users 30 --spawn-rate 5 --run-time 60s \\
        --host http://localhost:8000
"""

from __future__ import annotations

import uuid

from locust import HttpUser, between, events, task

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MCP_PATH = "/mcp/v1"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _jsonrpc(method: str, params: dict | None = None) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params or {},
    }


def _post_mcp(client, name: str, payload: dict) -> None:
    """POST to MCP endpoint, parse SSE response, mark pass/fail."""
    with client.post(
        MCP_PATH,
        json=payload,
        headers=HEADERS,
        name=name,
        stream=True,
        catch_response=True,
    ) as resp:
        if resp.status_code == 429:
            resp.success()  # expected under load — not a server error
            return
        if resp.status_code not in (200, 202):
            resp.failure(f"HTTP {resp.status_code}")
            return
        try:
            raw = resp.content.decode("utf-8", errors="replace")
            if "jsonrpc" in raw or "result" in raw or "error" in raw:
                resp.success()
            else:
                resp.failure(f"No JSON-RPC in response: {raw[:200]}")
        except Exception as exc:
            resp.failure(str(exc))


# ---------------------------------------------------------------------------
# User classes
# ---------------------------------------------------------------------------


class HealthUser(HttpUser):
    """Simulates Kubernetes liveness/readiness probes — pure HTTP, no MCP."""

    wait_time = between(0.5, 1.5)
    weight = 1  # fewer of these — probes are lightweight

    @task(3)
    def healthz(self):
        self.client.get("/healthz", name="GET /healthz")

    @task(1)
    def readyz(self):
        self.client.get("/readyz", name="GET /readyz")


class MCPLightUser(HttpUser):
    """Simulates a client doing cheap MCP calls (tools/list)."""

    wait_time = between(1, 3)
    weight = 2

    @task
    def tools_list(self):
        _post_mcp(
            self.client,
            "MCP tools/list",
            _jsonrpc("tools/list"),
        )


class MCPHeavyUser(HttpUser):
    """Simulates a user doing real tool calls — search + detail lookups."""

    wait_time = between(2, 5)
    weight = 3

    # Representative search terms a forensics analyst might use
    _keywords = [
        "memory",
        "file system",
        "network artifacts",
        "registry",
        "browser history",
        "volatile data",
    ]
    _idx = 0

    @task(3)
    def search(self):
        kw = self._keywords[MCPHeavyUser._idx % len(self._keywords)]
        MCPHeavyUser._idx += 1
        _post_mcp(
            self.client,
            "MCP tools/call solveit_search",
            _jsonrpc(
                "tools/call",
                {"name": "solveit_search", "arguments": {"keywords": kw}},
            ),
        )

    @task(2)
    def get_technique(self):
        _post_mcp(
            self.client,
            "MCP tools/call solveit_get_technique",
            _jsonrpc(
                "tools/call",
                {
                    "name": "solveit_get_technique",
                    "arguments": {"technique_id": "SIT-0001"},
                },
            ),
        )


# ---------------------------------------------------------------------------
# Summary hook — prints key stats when test ends
# ---------------------------------------------------------------------------


@events.quitting.add_listener
def on_quitting(environment, **kwargs):
    stats = environment.stats
    total = stats.total
    print("\n=== Stress Test Summary ===")
    print(f"  Total requests : {total.num_requests}")
    print(f"  Failures       : {total.num_failures}")
    print(f"  Median (ms)    : {total.median_response_time}")
    print(f"  95th pct (ms)  : {total.get_response_time_percentile(0.95)}")
    print(f"  RPS            : {total.current_rps:.1f}")
    print("===========================\n")
