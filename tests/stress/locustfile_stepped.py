"""
Stepped load test for mcp-chassis (SOLVE-IT MCP Server).

Ramps users in steps: 10 -> 25 -> 50 -> 75 -> 100 -> 150 -> 200
Each step runs for 30 seconds before adding more users.
This finds the inflection point where latency or failure rate climbs.

Primary tool under test: solveit_search (high weight).
Secondary tool: solveit_get_technique.

Run:
    locust -f tests/stress/locustfile_stepped.py --headless \\
        --users 200 --spawn-rate 999 \\
        --run-time 240s \\
        --host http://localhost:8000 \\
        --html /tmp/locust_stepped_report.html
"""

from __future__ import annotations

import uuid

from locust import HttpUser, between, events, task
from locust.env import Environment
from locust.runners import MasterRunner, WorkerRunner

# ---------------------------------------------------------------------------
# Step shape — inject users in stages
# ---------------------------------------------------------------------------

STEPS = [
    (10, 30),  # (users, seconds at this level)
    (25, 30),
    (50, 30),
    (75, 30),
    (100, 30),
    (150, 30),
    (200, 30),
]

_step_index = 0
_step_start = 0.0


@events.init.add_listener
def on_init(environment: Environment, **kwargs):
    if not isinstance(environment.runner, (MasterRunner, WorkerRunner)):
        import gevent

        gevent.spawn(_step_loop, environment)


def _step_loop(environment: Environment):
    import time

    import gevent

    global _step_index, _step_start
    _step_start = time.monotonic()

    while True:
        gevent.sleep(1)
        _advance_step(environment)


def _advance_step(environment: Environment, **kwargs):
    """Advance to the next load step when the current step duration has elapsed."""
    global _step_index, _step_start
    import time

    if isinstance(environment.runner, (MasterRunner, WorkerRunner)):
        return  # distributed mode — skip

    runner = environment.runner
    if runner is None:
        return

    now = time.monotonic()
    if _step_index >= len(STEPS):
        return

    target_users, duration = STEPS[_step_index]

    # First call: initialise and spawn the first wave
    if _step_index == 0 and runner.user_count == 0:
        _step_start = now
        print(f"\n>>> Step 1/{len(STEPS)}: ramping to {target_users} users")
        runner.start(target_users, spawn_rate=999)
        return

    if now - _step_start >= duration:
        _step_index += 1
        if _step_index >= len(STEPS):
            print("\n>>> All steps complete.")
            return
        target_users, duration = STEPS[_step_index]
        _step_start = now
        print(f"\n>>> Step {_step_index + 1}/{len(STEPS)}: ramping to {target_users} users")
        runner.start(target_users, spawn_rate=999)


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


def _call(client, label: str, tool: str, args: dict | None = None):
    payload = _jsonrpc("tools/call", {"name": tool, "arguments": args or {}})
    with client.post(
        MCP_PATH,
        json=payload,
        headers=HEADERS,
        name=f"tools/call {tool}",
        stream=True,
        catch_response=True,
    ) as resp:
        if resp.status_code == 429:
            resp.success()  # rate limited — expected, not a crash
            return
        if resp.status_code not in (200, 202):
            resp.failure(f"HTTP {resp.status_code}")
            return
        raw = resp.content.decode("utf-8", errors="replace")
        if "jsonrpc" in raw or "result" in raw or "error" in raw:
            resp.success()
        else:
            resp.failure(f"No JSON-RPC body: {raw[:120]}")


# ---------------------------------------------------------------------------
# User class
# ---------------------------------------------------------------------------


class SolveItUser(HttpUser):
    """Cycles through SOLVE-IT tools with realistic weights."""

    wait_time = between(1, 3)

    # --- Lightweight / common ---

    @task(8)
    def search(self):
        terms = ["memory", "file system", "network", "registry", "browser", "volatile"]
        kw = terms[hash(str(id(self))) % len(terms)]
        _call(self.client, "solveit_search", "solveit_search", {"keywords": kw})

    @task(5)
    def tools_list(self):
        with self.client.post(
            MCP_PATH,
            json=_jsonrpc("tools/list"),
            headers=HEADERS,
            name="tools/list",
            stream=True,
            catch_response=True,
        ) as resp:
            if resp.status_code == 429:
                resp.success()
                return
            if resp.status_code in (200, 202):
                resp.success()
            else:
                resp.failure(f"HTTP {resp.status_code}")

    # --- Detail lookups ---

    @task(6)
    def get_technique(self):
        _call(
            self.client,
            "solveit_get_technique",
            "solveit_get_technique",
            {"technique_id": "SIT-0001"},
        )

    @task(4)
    def get_weakness_details(self):
        _call(
            self.client, "get_weakness_details", "get_weakness_details", {"weakness_id": "SIW-0001"}
        )

    @task(4)
    def get_mitigation_details(self):
        _call(
            self.client,
            "get_mitigation_details",
            "get_mitigation_details",
            {"mitigation_id": "SIM-0001"},
        )

    @task(3)
    def get_citation(self):
        _call(self.client, "get_citation", "get_citation", {"citation_id": "DFCite-0001"})

    @task(2)
    def resolve_inline_citations(self):
        _call(
            self.client,
            "resolve_inline_citations",
            "resolve_inline_citations",
            {"text": "See DFCite-0001 and DFCite-0002 for details."},
        )

    # --- Relationship traversal ---

    @task(3)
    def get_mitigations_for_technique(self):
        _call(
            self.client,
            "get_mitigations_for_technique",
            "get_mitigations_for_technique",
            {"technique_id": "SIT-0001"},
        )

    @task(3)
    def get_weaknesses_for_technique(self):
        _call(
            self.client,
            "get_weaknesses_for_technique",
            "get_weaknesses_for_technique",
            {"technique_id": "SIT-0001"},
        )

    @task(3)
    def get_mitigations_for_weakness(self):
        _call(
            self.client,
            "get_mitigations_for_weakness",
            "get_mitigations_for_weakness",
            {"weakness_id": "SIW-0001"},
        )

    @task(3)
    def get_techniques_for_weakness(self):
        _call(
            self.client,
            "get_techniques_for_weakness",
            "get_techniques_for_weakness",
            {"weakness_id": "SIW-0001"},
        )

    @task(2)
    def get_weaknesses_for_mitigation(self):
        _call(
            self.client,
            "get_weaknesses_for_mitigation",
            "get_weaknesses_for_mitigation",
            {"mitigation_id": "SIM-0001"},
        )

    @task(2)
    def get_techniques_for_mitigation(self):
        _call(
            self.client,
            "get_techniques_for_mitigation",
            "get_techniques_for_mitigation",
            {"mitigation_id": "SIM-0001"},
        )

    # --- Objectives ---

    @task(3)
    def list_objectives(self):
        _call(self.client, "list_objectives", "list_objectives")

    @task(2)
    def get_techniques_for_objective(self):
        _call(
            self.client,
            "get_techniques_for_objective",
            "get_techniques_for_objective",
            {"objective_id": "OBJ-001"},
        )

    @task(2)
    def get_objectives_for_technique(self):
        _call(
            self.client,
            "get_objectives_for_technique",
            "get_objectives_for_technique",
            {"technique_id": "SIT-0001"},
        )

    # --- Bulk (expensive — low weight) ---

    @task(2)
    def get_all_techniques_with_name_and_id(self):
        _call(
            self.client,
            "get_all_techniques_with_name_and_id",
            "get_all_techniques_with_name_and_id",
        )

    @task(2)
    def get_all_weaknesses_with_name_and_id(self):
        _call(
            self.client,
            "get_all_weaknesses_with_name_and_id",
            "get_all_weaknesses_with_name_and_id",
        )

    @task(2)
    def get_all_mitigations_with_name_and_id(self):
        _call(
            self.client,
            "get_all_mitigations_with_name_and_id",
            "get_all_mitigations_with_name_and_id",
        )

    @task(1)
    def get_all_techniques_with_full_detail(self):
        _call(
            self.client,
            "get_all_techniques_with_full_detail",
            "get_all_techniques_with_full_detail",
        )

    @task(1)
    def get_all_weaknesses_with_full_detail(self):
        _call(
            self.client,
            "get_all_weaknesses_with_full_detail",
            "get_all_weaknesses_with_full_detail",
        )

    @task(1)
    def get_all_mitigations_with_full_detail(self):
        _call(
            self.client,
            "get_all_mitigations_with_full_detail",
            "get_all_mitigations_with_full_detail",
        )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


@events.quitting.add_listener
def on_quitting(environment, **kwargs):
    stats = environment.stats
    print("\n=== Stepped Load Test Summary ===")
    print(f"  Steps run      : {len(STEPS)} (10->25->50->75->100->150->200 users)")
    print(f"  Total requests : {stats.total.num_requests}")
    print(
        f"  Failures       : {stats.total.num_failures} "
        f"({100 * stats.total.num_failures / max(stats.total.num_requests, 1):.1f}%)"
    )
    print(f"  Median (ms)    : {stats.total.median_response_time}")
    print(f"  95th pct (ms)  : {stats.total.get_response_time_percentile(0.95)}")
    print(f"  Peak RPS       : {stats.total.current_rps:.1f}")
    print("")
    print("  Per-tool 95th percentile:")
    for name, entry in sorted(stats.entries.items(), key=lambda x: x[1].num_requests, reverse=True):
        p95 = entry.get_response_time_percentile(0.95)
        fails = entry.num_failures
        print(f"    {name[1]:<50} p95={p95:>5}ms  reqs={entry.num_requests:>5}  fails={fails}")
    print("=================================\n")
