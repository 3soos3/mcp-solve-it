"""Webhook emitter for the FSS Observer dashboard.

Activated by MCP_AUDIT_WEBHOOK_URL.  Posts one JSON record per event
to the observer service running in the cluster.  Fire-and-forget via a
daemon thread — never blocks the tool call path.  No-op when the env
var is unset.
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import urllib.request
from typing import Any

_URL     = os.environ.get("MCP_AUDIT_WEBHOOK_URL", "")
_VARIANT = os.environ.get("FSS_VARIANT", "unknown")
_Q: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=2000)


def _worker() -> None:
    while True:
        try:
            record = _Q.get(timeout=2)
            req = urllib.request.Request(
                _URL,
                data=json.dumps(record, default=str).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass


if _URL:
    _t = threading.Thread(target=_worker, daemon=True, name="fss-observer")
    _t.start()


def emit(event_type: str, **fields: Any) -> None:
    if not _URL:
        return
    record: dict[str, Any] = {
        "type": event_type,
        "variant": _VARIANT,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **fields,
    }
    try:
        _Q.put_nowait(record)
    except queue.Full:
        pass
