"""Image-level OTel export tests — real in-process OTLP gRPC receiver.

Starts a minimal gRPC OTLP collector in the test process, runs the live
container with --network=host pointing at 127.0.0.1:{port}, makes one tool
call, then reads the actual spans and metrics the container exported.

No extra container images required — the proto stubs and grpcio are already
bundled with opentelemetry-exporter-otlp-proto-grpc.

Networking: uses --network=host so the container shares the host loopback,
which is the most portable way to reach an in-process gRPC server from a container.

Known gap: start_span() in server.py accepts **attributes kwargs but does not
forward them to the real OTel tracer, so tool.name is absent from span
attributes.  Tests here reflect what the server actually emits today.
"""

from __future__ import annotations

import json
import socket
import subprocess
import threading
from concurrent import futures
from typing import Any

import grpc
import pytest
from opentelemetry.proto.collector.metrics.v1 import (
    metrics_service_pb2,
    metrics_service_pb2_grpc,
)
from opentelemetry.proto.collector.trace.v1 import (
    trace_service_pb2,
    trace_service_pb2_grpc,
)

from .image_configs import FAST_FAIL

_OTEL_ENABLED = "MCP_OTEL_ENABLED=true"


# ── Proto helpers ─────────────────────────────────────────────────────────────


def _decode_attrs(kvs: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kv in kvs:
        which = kv.value.WhichOneof("value")
        if which == "string_value":
            out[kv.key] = kv.value.string_value
        elif which == "int_value":
            out[kv.key] = kv.value.int_value
        elif which == "double_value":
            out[kv.key] = kv.value.double_value
        elif which == "bool_value":
            out[kv.key] = kv.value.bool_value
    return out


def _find_metric(metric_requests: list[Any], name: str) -> Any | None:
    for req in metric_requests:
        for rm in req.resource_metrics:
            for sm in rm.scope_metrics:
                for m in sm.metrics:
                    if m.name == name:
                        return m
    return None


def _counter_value(metric: Any, tool_name: str | None = None) -> int | None:
    # The oneof data field is accessed directly as metric.sum (not metric.data.sum)
    for dp in metric.sum.data_points:
        if tool_name is None or _decode_attrs(dp.attributes).get("tool.name") == tool_name:
            return dp.as_int
    return None


def _histogram_count(metric: Any, tool_name: str | None = None) -> int | None:
    for dp in metric.histogram.data_points:
        if tool_name is None or _decode_attrs(dp.attributes).get("tool.name") == tool_name:
            return dp.count
    return None


def _gauge_value(metric: Any) -> float | None:
    for dp in metric.gauge.data_points:
        which = dp.WhichOneof("value")
        if which == "as_double":
            return dp.as_double
        if which == "as_int":
            return float(dp.as_int)
    return None


def _received_metric_names(metric_requests: list[Any]) -> list[str]:
    names = []
    for req in metric_requests:
        for rm in req.resource_metrics:
            for sm in rm.scope_metrics:
                for m in sm.metrics:
                    names.append(m.name)
    return names


# ── In-process OTLP gRPC receiver ────────────────────────────────────────────


class _OTLPReceiver(
    trace_service_pb2_grpc.TraceServiceServicer,
    metrics_service_pb2_grpc.MetricsServiceServicer,
):
    """Minimal gRPC OTLP collector that stores every span and metric it receives."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.spans: list[Any] = []
        self.span_resources: list[Any] = []
        self.metric_requests: list[Any] = []

    def Export(self, request: Any, context: Any) -> Any:  # noqa: N802
        if hasattr(request, "resource_spans"):
            with self._lock:
                for rs in request.resource_spans:
                    for ss in rs.scope_spans:
                        for span in ss.spans:
                            self.spans.append(span)
                            self.span_resources.append(rs.resource)
            return trace_service_pb2.ExportTraceServiceResponse()
        else:
            with self._lock:
                self.metric_requests.append(request)
            return metrics_service_pb2.ExportMetricsServiceResponse()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


# ── Container helper ──────────────────────────────────────────────────────────


def _run_tool_with_receiver(
    image: str,
    tool: str,
    collector_port: int,
    extra_env: tuple[str, ...] = (),
    timeout: int = 45,
) -> dict[str, Any]:
    """Run one tool call; graceful shutdown flushes OTel spans+metrics to the receiver.

    Uses --network=host so the container shares the host loopback and can reach
    127.0.0.1:{collector_port} without additional network configuration.
    """
    endpoint = f"MCP_OTEL_ENDPOINT=http://127.0.0.1:{collector_port}"
    cmd = [
        "podman",
        "run",
        "--rm",
        "-i",
        "--network=host",
        "-e",
        "MCP_TRANSPORT=stdio",
        "-e",
        endpoint,
    ]
    for e in extra_env:
        cmd += ["-e", e]
    cmd.append(image)

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    def _readline(t: float) -> bytes | None:
        result: list[bytes | None] = [None]

        def _r() -> None:
            try:
                result[0] = proc.stdout.readline()  # type: ignore[union-attr]
            except Exception:
                pass

        th = threading.Thread(target=_r, daemon=True)
        th.start()
        th.join(t)
        return result[0]

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
                    "clientInfo": {"name": "otel-collector-test", "version": "1.0"},
                },
            }
        )
        if not _readline(15):
            proc.kill()
            return {"_error": "no initialize response"}

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
            raw = _readline(float(timeout))
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
        return {"_error": str(exc)}

    # Graceful shutdown: EOF on stdin → server exits → OTel force_flush →
    # spans and metrics reach the receiver before proc terminates.
    try:
        proc.stdin.close()  # type: ignore[union-attr]
    except Exception:
        pass
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    return response if response else {"_error": "no id=2 response"}


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="class")
def otlp_collector() -> Any:
    """Start a gRPC OTLP server once for the whole class; stop it after."""
    receiver = _OTLPReceiver()
    port = _free_port()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    trace_service_pb2_grpc.add_TraceServiceServicer_to_server(receiver, server)
    metrics_service_pb2_grpc.add_MetricsServiceServicer_to_server(receiver, server)
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    yield receiver, port
    server.stop(grace=2)


@pytest.fixture(scope="class")
def live_receiver(live_image: str, otlp_collector: Any) -> _OTLPReceiver:
    """Make one solveit_status call; return the populated receiver.

    Class-scoped: the container runs once; all tests in the class share
    the receiver that was populated by that single call.
    """
    receiver, port = otlp_collector
    resp = _run_tool_with_receiver(
        live_image,
        "solveit_status",
        port,
        extra_env=(FAST_FAIL, _OTEL_ENABLED),
    )
    assert "_error" not in resp, f"Container failed to respond: {resp}"
    return receiver


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.slow
class TestOTelExports:
    """Verify that spans and metrics actually reach a real OTLP gRPC receiver."""

    @pytest.fixture(autouse=True)
    def _set_receiver(self, live_receiver: _OTLPReceiver) -> None:
        self.receiver = live_receiver

    # ── Trace ─────────────────────────────────────────────────────────────────

    def test_one_span_emitted_per_tool_call(self) -> None:
        assert len(self.receiver.spans) == 1, (
            f"Expected 1 span, got {len(self.receiver.spans)}: "
            f"{[s.name for s in self.receiver.spans]}"
        )

    def test_span_name_is_mcp_tool_call(self) -> None:
        assert self.receiver.spans[0].name == "mcp.tool.call"

    def test_span_has_fss_error_code_none(self) -> None:
        attrs = _decode_attrs(self.receiver.spans[0].attributes)
        assert attrs.get("fss.error_code") == "none", (
            f"Expected fss.error_code='none' on successful call, got: {attrs}"
        )

    def test_span_has_fss_transaction_id(self) -> None:
        attrs = _decode_attrs(self.receiver.spans[0].attributes)
        assert "fss.transaction_id" in attrs, f"Missing fss.transaction_id in: {attrs}"
        assert len(attrs["fss.transaction_id"]) == 36, "Expected UUID-length transaction_id"

    def test_span_resource_service_name(self) -> None:
        res_attrs = _decode_attrs(self.receiver.span_resources[0].attributes)
        assert res_attrs.get("service.name") == "mcp-solve-it", (
            f"Unexpected span resource attributes: {res_attrs}"
        )

    def test_span_resource_environment_default(self) -> None:
        res_attrs = _decode_attrs(self.receiver.span_resources[0].attributes)
        assert res_attrs.get("deployment.environment") == "production"

    # ── Metrics ───────────────────────────────────────────────────────────────

    def test_call_counter_received(self) -> None:
        m = _find_metric(self.receiver.metric_requests, "mcp.tool.calls")
        assert m is not None, (
            "mcp.tool.calls not received. "
            f"Got: {_received_metric_names(self.receiver.metric_requests)}"
        )

    def test_call_counter_value_is_one(self) -> None:
        m = _find_metric(self.receiver.metric_requests, "mcp.tool.calls")
        assert m is not None
        val = _counter_value(m, tool_name="solveit_status")
        assert val == 1, f"Expected call counter=1, got {val}"

    def test_duration_histogram_received(self) -> None:
        m = _find_metric(self.receiver.metric_requests, "mcp.tool.duration")
        assert m is not None, (
            "mcp.tool.duration not received. "
            f"Got: {_received_metric_names(self.receiver.metric_requests)}"
        )

    def test_duration_histogram_has_one_observation(self) -> None:
        m = _find_metric(self.receiver.metric_requests, "mcp.tool.duration")
        assert m is not None
        count = _histogram_count(m, tool_name="solveit_status")
        assert count == 1, f"Expected 1 duration observation, got {count}"

    def test_expected_metric_names_exported(self) -> None:
        """All per-call metrics must be present after one solveit_status call."""
        names = set(_received_metric_names(self.receiver.metric_requests))
        expected = {
            "mcp.tool.calls",
            "mcp.tool.duration",
            "mcp.request.size",
            "mcp.response.size",
            "mcp.provenance.responses",
        }
        missing = expected - names
        assert not missing, f"Missing expected metrics: {missing}. Got: {names}"

    def test_metrics_resource_matches_span_resource(self) -> None:
        """Tracer and meter built from same Resource — service.name must agree."""
        span_svc = _decode_attrs(self.receiver.span_resources[0].attributes).get("service.name")
        for req in self.receiver.metric_requests:
            for rm in req.resource_metrics:
                metric_svc = _decode_attrs(rm.resource.attributes).get("service.name")
                assert metric_svc == span_svc, (
                    f"service.name mismatch: span={span_svc!r} metric={metric_svc!r}"
                )
