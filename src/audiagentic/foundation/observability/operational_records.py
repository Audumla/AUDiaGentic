"""Append-only operational sidecar record helper."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.logging.redaction import find_denylisted_key
from audiagentic.foundation.time import now_iso_z

_opr_error = make_error_factory("VAL", "OPR", "operational-record-validation")
_con_opr_error = make_error_factory("CON", "OPR", "operational-record-constraint")

_OPR_LOCKS: dict[Path, threading.Lock] = {}
_OPR_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    resolved = path.resolve()
    with _OPR_LOCKS_GUARD:
        lock = _OPR_LOCKS.get(resolved)
        if lock is None:
            lock = threading.Lock()
            _OPR_LOCKS[resolved] = lock
        return lock


def append_operational_record(path: Path, record: dict[str, Any]) -> None:
    """Append a single operational record to an ndjson sidecar file.

    O(1) append semantics — opens in 'a' mode, writes one JSON line, flushes/fsyncs.
    Thread-safe via per-path lock registry. Multi-process locking is out of scope.

    Requires:
        - ``correlation_id`` key must be present (value may be None).
        - No sensitive-shaped field names (prompt-body, output, api_key, …)
          anywhere in the record — nested mappings and sequences included.

    Raises:
        AudiaGenticError: VAL-OPR-001 if correlation_id is missing.
        AudiaGenticError: CON-OPR-002 if a denylisted key is present at any depth.
    """
    if "correlation_id" not in record:
        raise _opr_error(
            1,
            "Operational record is missing required 'correlation_id' key",
            keys=list(record.keys()),
        )

    denied = find_denylisted_key(record)
    if denied is not None:
        raise _con_opr_error(
            2,
            f"Operational record contains denylisted field {denied!r}",
            denied_field=denied,
        )

    if "timestamp" not in record:
        record["timestamp"] = now_iso_z()

    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock_for(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
