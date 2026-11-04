"""Convert a branch that still appended to the frozen baseline into per-event files.

A branch cut before the per-event store, or recorded by an older ledger tool, carries new rows appended to the shared
``CURRENT_RELEASE_LEDGER.ndjson``. This moves each appended row into its own event file and restores the baseline to
what the branch's merge base with ``base_ref`` holds, so the branch no longer changes that file and merges with no
ledger conflict.

It refuses rather than guesses: the working baseline must be the merge base's content plus appended rows only (an
edited, deleted or reordered row, or conflict markers, stop it), every appended row must pass the strict event
contract and not conflict with any baseline, event or released identity, and nothing is written until the whole set
is proven convertible. Run it before merging or rebasing onto the frozen main, while the branch's rows are intact.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from audiagentic.components.ledger.current_events import (
    event_identity,
    event_path,
    event_write_lock,
    parse_event_file,
    released_events,
    write_event,
)
from audiagentic.components.ledger.paths import current_ledger_path
from audiagentic.components.ledger.validation import validate_persisted_event
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_text


def _refuse(message: str, **details: Any) -> AudiaGenticError:
    return AudiaGenticError(code="CON-LEDGER-010", kind="release", message=message, details=details)


def _git(project_root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "-C", str(project_root), *args], capture_output=True, check=False)


def _merge_base(project_root: Path, base_ref: str) -> str:
    done = _git(project_root, "merge-base", "HEAD", base_ref)
    if done.returncode != 0:
        raise _refuse("no merge base with the base ref; cannot tell which rows the branch added", ref=base_ref)
    return done.stdout.decode().strip()


def _base_text(project_root: Path, base: str, baseline: Path) -> str | None:
    """The baseline at ``base``; None when the path genuinely does not exist there (any other failure raises)."""
    spec = f"{base}:{baseline.resolve().relative_to(project_root.resolve()).as_posix()}"
    if _git(project_root, "cat-file", "-e", spec).returncode != 0:
        return None
    shown = _git(project_root, "show", spec)
    if shown.returncode != 0:
        raise _refuse("the baseline could not be read at the merge base", ref=base)
    return shown.stdout.decode("utf-8")


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and line.strip() != "[]"]


def convert_baseline_appends(project_root: Path, base_ref: str = "origin/main") -> dict[str, Any]:
    """Move rows appended to the baseline since the merge base into event files; restore the baseline."""
    baseline = current_ledger_path(project_root)
    if not baseline.exists():
        return {"converted": [], "rejected": [], "restored": False}
    base = _merge_base(project_root, base_ref)
    base_text = _base_text(project_root, base, baseline)
    base_lines = _lines(base_text or "")
    observed = baseline.read_bytes()
    working = _lines(observed.decode("utf-8"))
    if working[:len(base_lines)] != base_lines:
        raise _refuse("the baseline was edited, not only appended to (rows changed, were removed or reordered, or a "
                      "merge left markers); restore it to the merge base and re-record the new rows", ref=base)
    appended = working[len(base_lines):]

    # Prove the whole set before writing anything.
    base_ids = {json.loads(line).get("event-id"): json.loads(line) for line in base_lines}
    released = released_events(project_root)
    plan: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    seen: dict[str, dict[str, Any]] = {}
    for number, line in enumerate(appended, len(base_lines) + 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            rejected.append({"line": str(number), "event-id": "", "reason": "invalid JSON"})
            continue
        event_id = row.get("event-id") if isinstance(row, dict) else None
        try:
            if not isinstance(event_id, str) or not event_id:
                raise AudiaGenticError(code="CON-LEDGER-002", kind="release", message="appended row has no event-id")
            validate_persisted_event(row, location=f"baseline line {number}", role="current")
            for known in (base_ids.get(event_id), released.get(event_id), seen.get(event_id)):
                if known is not None and event_identity(known) != event_identity(row):
                    raise _refuse("appended row conflicts with a known event of the same id", **{"event-id": event_id})
            existing = event_path(project_root, event_id)
            if existing.exists() and event_identity(parse_event_file(existing, existing.read_text(encoding="utf-8"))) \
                    != event_identity(row):
                raise _refuse("appended row conflicts with an existing event file", **{"event-id": event_id})
        except AudiaGenticError as error:
            rejected.append({"line": str(number), "event-id": str(event_id or ""), "reason": error.code})
            continue
        seen[event_id] = row
        if event_id not in base_ids:
            plan.append(row)
    if rejected:
        return {"converted": [], "rejected": rejected, "restored": False}

    for row in plan:
        with event_write_lock(project_root, row["event-id"]):
            path, _ = write_event(project_root, row)
            parse_event_file(path, path.read_text(encoding="utf-8"))  # verify before the baseline is touched
    if baseline.read_bytes() != observed:
        raise _refuse("the baseline changed while it was being converted; nothing was restored", ref=base)
    if base_text is None:
        baseline.unlink()  # the merge base never had a baseline: restore its absence
    else:
        atomic_write_text(baseline, base_text)
    return {"converted": [row["event-id"] for row in plan], "rejected": [], "restored": True}


__all__ = ["convert_baseline_appends"]
