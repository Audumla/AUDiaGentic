"""Dead-letter record module for async event-handler failures (EDJ12).

Records a durable, redacted entry whenever a bus handler fires and fails.
Used by EDJ02 (step 5), EDJ04 (step 5), and referenced in EDJ05 notes.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error_factory
from audiagentic.foundation.observability.operational_records import append_operational_record
from audiagentic.foundation.time import now_iso_z

logger = logging.getLogger(__name__)

_dl_val = make_error_factory("VAL", "DL", "dead-letter-validation")
_dl_io = make_error_factory("IO", "DL", "dead-letter-io")

_DEAD_LETTER_REQUIRED_KEYS = frozenset(
    (
        "event_type",
        "payload_summary",
        "metadata",
        "trigger_id",
        "job_id",
        "error_code",
        "error_message",
        "correlation_id",
    )
)

_DEAD_LETTER_PATH = Path(".audiagentic") / "runtime" / "agent-jobs" / "dead-letter.ndjson"


def dead_letter_path(project_root: Path) -> Path:
    """Return the dead-letter ndjson path for a project."""
    return project_root / _DEAD_LETTER_PATH


def write_dead_letter(project_root: Path, record: dict[str, Any]) -> None:
    """Write a single dead-letter entry via the shared operational-record helper.

    Ensures the record has all required keys, fills in ``timestamp`` and
    ``correlation_id`` if absent, enforces the 500-char payload-summary cap,
    then delegates to :func:`append_operational_record`.

    Raises:
        AudiaGenticError: VAL-DL-002 if a required field is missing after defaults.
        AudiaGenticError: IO-DL-001 on write failure.
    """
    # Fill structural defaults
    if "timestamp" not in record:
        record["timestamp"] = now_iso_z()
    if record.get("correlation_id") is None:
        record["correlation_id"] = ""

    # Enforce payload-summary length cap
    summary = record.get("payload_summary", "")
    if isinstance(summary, str) and len(summary) > 500:
        record["payload_summary"] = summary[:497] + "..."

    # Validate required keys are present
    missing = _DEAD_LETTER_REQUIRED_KEYS - set(record.keys())
    if missing:
        raise _dl_val(
            2,
            f"Dead-letter record is missing required field(s): {', '.join(sorted(missing))}",
            missing_fields=sorted(missing),
        )

    # Ensure metadata is a dict (never None for this field)
    if not isinstance(record.get("metadata"), dict):
        record["metadata"] = {}

    try:
        append_operational_record(dead_letter_path(project_root), record)
    except AudiaGenticError:
        raise
    except Exception as cause:  # noqa: BLE001 — external boundary (disk I/O)
        logger.error(
            "Failed to write dead-letter record",
            exc_info=True,
        )
        raise _dl_io(
            1,
            "Dead-letter write failed",
        ) from cause


def read_dead_letters(project_root: Path) -> list[dict[str, Any]]:
    """Read all dead-letter entries from the ndjson file (if it exists).

    Returns an empty list if the file does not exist or is empty. Malformed
    JSON lines are logged and skipped.
    """
    path = dead_letter_path(project_root)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            records.append(json.loads(stripped))
        except json.JSONDecodeError:
            logger.warning(
                "Skipping malformed dead-letter line %d",
                i,
                exc_info=True,
            )
    return records
