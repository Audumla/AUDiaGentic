"""Read-only detection of stuck dispatch from the gateway's work index.

A request that waits behind a running one is queued, not stuck (a gpt-auto review can hold the lane for an
hour). Stuck means nothing is running yet a request has sat in a phase longer than that phase can take. The
index carries only phase and two timestamps, so this is deliberately coarse: it catches a gateway that cannot
start work at all (missing dependency, browser down) and leaves per-request progress to the activity lease.
Thresholds are per phase, not one timeout; a first gpt-auto job after a restart legitimately spends minutes in
``claimed`` while it opens a browser tab.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ADMISSION_STALL_SECONDS = 120.0   # admitted, lane idle, nobody claimed it
START_STALL_SECONDS = 900.0       # claimed, never reached running (cold browser tab included)


@dataclass(frozen=True)
class Finding:
    code: str            # admission-stalled | start-stalled
    request_id: str
    age_seconds: float
    detail: str


@dataclass(frozen=True)
class DispatchReport:
    entries: int
    running: int
    queued_behind: int
    findings: tuple[Finding, ...]


def _seconds(stamp: Any) -> float | None:
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def read_entries(service_root: Path) -> list[dict[str, Any]]:
    """Index entries as plain mappings. Unreadable files are skipped; nothing is moved or written."""
    entries = []
    for path in sorted((service_root / "active-work").glob("req_*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and isinstance(value.get("request-id"), str):
            entries.append(value)
    return entries


def classify(entries: list[dict[str, Any]], now: float) -> DispatchReport:
    running = [e for e in entries if e.get("phase") == "running"]
    findings: list[Finding] = []
    queued = 0
    for entry in entries:
        phase, request_id = entry.get("phase"), str(entry["request-id"])
        if phase == "admitted":
            admitted = _seconds(entry.get("admitted-at"))
            if running:
                queued += 1
            elif admitted is not None and now - admitted > ADMISSION_STALL_SECONDS:
                findings.append(Finding("admission-stalled", request_id, now - admitted,
                                        f"admitted {int(now - admitted)} s ago, the lane is idle and nothing claimed it"))
        elif phase == "claimed":
            claimed = _seconds(entry.get("claimed-at"))
            if claimed is not None and now - claimed > START_STALL_SECONDS:
                findings.append(Finding("start-stalled", request_id, now - claimed,
                                        f"claimed {int(now - claimed)} s ago and never started running"))
    return DispatchReport(len(entries), len(running), queued, tuple(findings))
