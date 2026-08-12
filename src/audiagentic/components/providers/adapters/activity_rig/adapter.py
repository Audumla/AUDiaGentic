from __future__ import annotations

import os
import time
from typing import Any


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    """Deterministic provider result; worker_host emits authenticated activity."""
    # Keep the controlled turn alive long enough for the worker host to emit
    # its configured progress sequence (the normal rig path is intentionally
    # instant, which would otherwise produce zero frames).
    if os.environ.get("AUDIAGENTIC_WORKER_ACTIVITY_SOURCES"):
        interval = float(os.environ.get("AUDIAGENTIC_WORKER_ACTIVITY_INTERVAL_SECONDS", "5"))
        time.sleep(max(0.1, interval * 3.2))
    if os.environ.get("AUDIAGENTIC_ACTIVITY_RIG_PAUSE") == "1":
        time.sleep(float(os.environ.get("AUDIAGENTIC_ACTIVITY_RIG_PAUSE_SECONDS", "1")))
    if os.environ.get("AUDIAGENTIC_ACTIVITY_RIG_STALL") == "1":
        time.sleep(float(os.environ.get("AUDIAGENTIC_ACTIVITY_RIG_STALL_SECONDS", "30")))
    return {"output": "ACTIVITY_RIG_OK:" + str(packet_ctx.get("prompt-body", ""))[:200], "status": "completed"}
