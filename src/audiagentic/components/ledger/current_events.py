"""The one reader and writer of current (unreleased) ledger events.

A new event is one tracked, write-once file ``<events-dir>/<sha256(event-id)>.json``. Two branches that record
different events therefore never touch the same path, and git needs no merge driver. The old shared
``CURRENT_RELEASE_LEDGER.ndjson`` is a frozen, read-only legacy baseline that this module reads and nothing writes.
Released events are those whose ids appear in the historical ledger; the current set is the loader's events minus
those ids, so a release changes only ``LEDGER.ndjson`` and never edits or deletes an event file.

Every reader goes through ``iter_events`` (working tree, or any git ref for a reproducible tagged release).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from audiagentic.components.ledger.paths import (
    current_ledger_path,
    historical_ledger_path,
    ledger_events_dir,
    ledger_runtime_dir,
)
from audiagentic.components.ledger.validation import load_persisted_events, validate_persisted_event
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_text
from audiagentic.foundation.system.process import StartupLock

#: Lifecycle annotations that are not part of an event's immutable identity.
_ANNOTATIONS = frozenset({"status", "release-id", "git-commits"})
_LEGACY_ID = "legacy-line-{line}-{digest}"


@contextmanager
def event_write_lock(project_root: Path, event_id: str) -> Iterator[None]:
    """Serialize the existence check and write of one event file across processes."""
    directory = ledger_runtime_dir(project_root) / "event-locks"
    directory.mkdir(parents=True, exist_ok=True)
    with StartupLock(directory / f"{event_file_name(event_id)}.lock", timeout=30.0):
        yield


def event_identity(event: dict[str, Any]) -> dict[str, Any]:
    """The immutable content of an event, excluding lifecycle annotations."""
    return {key: value for key, value in event.items() if key not in _ANNOTATIONS}


def event_file_name(event_id: str) -> str:
    """Portable, collision-free file name for an event id (ids may carry legacy punctuation)."""
    return hashlib.sha256(event_id.encode("utf-8")).hexdigest() + ".json"


def event_path(project_root: Path, event_id: str) -> Path:
    return ledger_events_dir(project_root) / event_file_name(event_id)


def event_text(event: dict[str, Any]) -> str:
    return json.dumps(event, indent=2, sort_keys=True) + "\n"


def write_event(project_root: Path, event: dict[str, Any]) -> tuple[Path, str]:
    """Write one event file atomically and write-once. Returns ``(path, "created" | "exists")``.

    The caller holds the per-event lock. The same id with different immutable content is an error, never an
    overwrite; ``git-commits`` is a mutable annotation and is excluded from the comparison.
    """
    path = event_path(project_root, event["event-id"])
    if path.exists():
        existing = parse_event_file(path, path.read_text(encoding="utf-8"))
        if event_identity(existing) != event_identity(event):
            raise AudiaGenticError(
                code="CON-FRAGMENT-001", kind="release",
                message="event already exists with different content",
                details={"event-id": event["event-id"]},
            )
        return path, "exists"
    atomic_write_text(path, event_text(event))
    return path, "created"


def parse_event_file(path: Path, text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AudiaGenticError(
            code="CON-LEDGER-004", kind="release", message="persisted ledger contains invalid JSON",
            details={"path": path.name},
        ) from exc
    event = validate_persisted_event(value, location=path.name, role="current")
    if event_file_name(event["event-id"]) != path.name:
        raise AudiaGenticError(
            code="CON-LEDGER-007", kind="release", message="event file name does not match its event-id",
            details={"path": path.name, "event-id": event["event-id"]},
        )
    return event


def _legacy_rows(text: str) -> list[dict[str, Any]]:
    """Rows of the frozen baseline, tolerant of the anomalies old tooling wrote.

    Never schema-validated and never rewritten. A row without an ``event-id`` gets a deterministic synthetic one
    (line number plus a digest of the line), computed on read, so it is stable, unique and never random.
    """
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.strip() == "[]":
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AudiaGenticError(
                code="CON-LEDGER-004", kind="release", message="persisted ledger contains invalid JSON",
                details={"path": "baseline", "line": number},
            ) from exc
        if not isinstance(value, dict):
            raise AudiaGenticError(
                code="CON-LEDGER-002", kind="release", message="persisted ledger entry is not an object",
                details={"location": f"baseline:{number}"},
            )
        if not isinstance(value.get("event-id"), str) or not value["event-id"]:
            digest = hashlib.sha256(line.encode("utf-8")).hexdigest()[:8]
            value = {**value, "event-id": _LEGACY_ID.format(line=number, digest=digest)}
        rows.append(value)
    return rows


class _WorkingTree:
    def __init__(self, project_root: Path) -> None:
        self.root = project_root

    def baseline(self) -> str:
        path = current_ledger_path(self.root)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def historical(self) -> list[dict[str, Any]]:
        return load_persisted_events(historical_ledger_path(self.root), role="historical")

    def event_files(self) -> list[tuple[str, str]]:
        return [(path.name, path.read_text(encoding="utf-8")) for path in _event_paths(self.root)]


class _GitRef:
    """The same three reads, taken from one git ref so a tagged release is reproducible."""

    def __init__(self, project_root: Path, ref: str) -> None:
        self.root, self.ref = project_root, ref

    def _git(self, *args: str, input_bytes: bytes | None = None) -> bytes:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(self.root), *args], input=input_bytes, capture_output=True, check=False)
        if done.returncode != 0:
            raise AudiaGenticError(
                code="CON-LEDGER-009", kind="release", message="ledger could not be read at the git ref",
                details={"ref": self.ref, "reason": done.stderr.decode(errors="replace")[:300]},
            )
        return done.stdout

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    def _blob(self, path: Path) -> str:
        spec = f"{self.ref}:{self._relative(path)}"
        probe = subprocess.run(  # noqa: S603
            ["git", "-C", str(self.root), "cat-file", "-e", spec], capture_output=True, check=False)
        return self._git("show", spec).decode("utf-8") if probe.returncode == 0 else ""

    def baseline(self) -> str:
        return self._blob(current_ledger_path(self.root))

    def historical(self) -> list[dict[str, Any]]:
        text = self._blob(historical_ledger_path(self.root))
        events: list[dict[str, Any]] = []
        for number, line in enumerate(text.splitlines(), 1):
            if line.strip() and line.strip() != "[]":
                events.append(validate_persisted_event(
                    json.loads(line), location=f"historical@{self.ref}:{number}", role="historical"))
        return events

    def event_files(self) -> list[tuple[str, str]]:
        directory = self._relative(ledger_events_dir(self.root))
        # Direct children only, regular files only (not symlinks), like the working-tree loader.
        listing = self._git("ls-tree", "-z", self.ref, f"{directory}/").decode("utf-8")
        names = []
        for entry in filter(None, listing.split("\0")):
            meta, _, name = entry.partition("\t")
            mode, kind, _sha = meta.split()
            if kind == "blob" and mode in ("100644", "100755") and name.endswith(".json"):
                names.append(name)
        names.sort()
        if not names:
            return []
        request = "".join(f"{self.ref}:{name}\n" for name in names).encode("utf-8")
        out = self._git("cat-file", "--batch", input_bytes=request)
        files: list[tuple[str, str]] = []
        position = 0
        for name in names:
            end = out.index(b"\n", position)
            header = out[position:end].split()
            size = int(header[2])
            files.append((Path(name).name, out[end + 1:end + 1 + size].decode("utf-8")))
            position = end + 1 + size + 1
        return files


def _event_paths(project_root: Path) -> list[Path]:
    """The event files of the working tree: direct regular files of the events directory, never symlinks."""
    directory = ledger_events_dir(project_root)
    if not directory.is_dir():
        return []
    root = directory.resolve()
    paths: list[Path] = []
    for path in sorted(directory.glob("*.json")):
        if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
            raise AudiaGenticError(
                code="CON-LEDGER-007", kind="release", message="event file is not a regular file of the events directory",
                details={"path": path.name},
            )
        paths.append(path)
    return paths


def _source(project_root: Path, ref: str | None) -> _WorkingTree | _GitRef:
    return _GitRef(project_root, ref) if ref else _WorkingTree(project_root)


def _merge(baseline: list[dict[str, Any]], recorded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Baseline in its own order, then events by (timestamp-utc, event-id); an id seen twice must be identical."""
    recorded = sorted(recorded, key=lambda event: (str(event.get("timestamp-utc") or ""), event["event-id"]))
    by_id: dict[str, dict[str, Any]] = {}
    for event in [*baseline, *recorded]:
        known = by_id.get(event["event-id"])
        if known is None:
            by_id[event["event-id"]] = event
        elif event_identity(known) != event_identity(event):
            raise AudiaGenticError(
                code="CON-LEDGER-008", kind="release", message="two ledger sources hold different content for one event-id",
                details={"event-id": event["event-id"]},
            )
    return list(by_id.values())


def iter_events(project_root: Path, *, ref: str | None = None) -> list[dict[str, Any]]:
    """All current-or-released events recorded in the working tree, or at ``ref`` (a ref name or a full sha).

    The returned dicts are the stored events unchanged, except that a legacy baseline row without an ``event-id``
    carries a deterministic synthetic one.
    """
    source = _source(project_root, ref)
    baseline = _legacy_rows(source.baseline())
    recorded = [parse_event_file(Path(name), text) for name, text in source.event_files()]
    return _merge(baseline, recorded)


def released_events(project_root: Path, *, ref: str | None = None) -> dict[str, dict[str, Any]]:
    """The historical ledger by event-id; a duplicated id with different content fails closed."""
    released: dict[str, dict[str, Any]] = {}
    for event in _source(project_root, ref).historical():
        known = released.setdefault(event["event-id"], event)
        if event_identity(known) != event_identity(event) or (
            known.get("release-id") != event.get("release-id")
        ):
            raise AudiaGenticError(
                code="CON-ARCHIVE-003", kind="release",
                message="historical ledger contains conflicting content for an event-id",
                details={"event-id": event["event-id"]},
            )
    return released


def reconcile(project_root: Path, *, ref: str | None = None) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Every recorded event plus the released ones, with the cross-source identity rules enforced once.

    The historical ledger is authoritative: an id present there with different immutable content than a recorded
    event is a conflict, never a silent resurrection or a mislabelled link. Returns ``(events, released_by_id)``.
    """
    released = released_events(project_root, ref=ref)
    events = iter_events(project_root, ref=ref)
    for event in events:
        prior = released.get(event["event-id"])
        if prior is not None and event_identity(prior) != event_identity(event):
            raise AudiaGenticError(
                code="CON-ARCHIVE-003", kind="release",
                message="current ledger has conflicting content for an archived event identity",
                details={"event-id": event["event-id"]},
            )
    return events, released


def pending_events(project_root: Path, *, ref: str | None = None) -> list[dict[str, Any]]:
    """Events not yet released: every event whose id is absent from the historical ledger."""
    events, released = reconcile(project_root, ref=ref)
    return [event for event in events if event["event-id"] not in released]


def anomalies(project_root: Path, *, ref: str | None = None) -> list[dict[str, str]]:
    """Legacy rows the strict schema would reject, reported (never hidden) for the audit view."""
    known = _known_classes()
    found: list[dict[str, str]] = []
    for event in _legacy_rows(_source(project_root, ref).baseline()):
        event_id = event["event-id"]
        if event_id.startswith("legacy-line-"):
            found.append({"event-id": event_id, "kind": "synthetic event-id"})
        if not event.get("timestamp-utc"):
            found.append({"event-id": event_id, "kind": "missing timestamp"})
        if event.get("change-class") not in known:
            found.append({"event-id": event_id, "kind": "unknown change-class"})
        if not event.get("user-summary-candidate"):
            found.append({"event-id": event_id, "kind": "missing user-summary-candidate"})
    return found


def _known_classes() -> set[str]:
    schema = json.loads((Path(__file__).parent / "contracts" / "change-event.schema.json").read_text(encoding="utf-8"))
    return set(schema["properties"]["change-class"]["enum"])


def event_files_in_tree(project_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Each tracked event file with its parsed event (for the few writers that annotate one event's own file)."""
    return [(path, parse_event_file(path, path.read_text(encoding="utf-8"))) for path in _event_paths(project_root)]


__all__: list[str] = [
    "anomalies", "event_file_name", "event_write_lock", "event_files_in_tree", "event_identity", "event_path", "event_text",
    "iter_events", "parse_event_file", "pending_events", "reconcile", "released_events", "write_event",
]
