"""Target parsing helpers for tagged interactive prompts."""
from __future__ import annotations

import logging
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)

DEFAULT_TARGET_KIND = "adhoc"


def _parse_target(value: str, *, adhoc_requested: bool) -> dict[str, Any]:
    # An adhoc tag supplies the default target kind, but an explicit typed
    # target such as ``target=packet:PKT-1`` still has to be honored.
    if adhoc_requested and ":" not in value:
        payload: dict[str, Any] = {"kind": "adhoc"}
        if value:
            payload["adhoc-id"] = value
        return payload
    if ":" not in value:
        raise AudiaGenticError(
            code="VAL-PPARSE-002",
            kind="agent-jobs",
            message="target directive must use kind:value",
            details={"value": value},
        )
    kind, ref = value.split(":", 1)
    if kind == "packet":
        return {"kind": "packet", "packet-id": ref}
    if kind == "job":
        return {"kind": "job", "job-id": ref}
    if kind == "artifact":
        if "/" in ref or ref.startswith("."):
            return {"kind": "artifact", "artifact-path": ref}
        return {"kind": "artifact", "artifact-id": ref}
    if kind == "adhoc":
        return {"kind": "adhoc", "adhoc-id": ref or None}
    raise AudiaGenticError(
        code="VAL-PPARSE-003",
        kind="agent-jobs",
        message="unknown target kind",
        details={"kind": kind},
    )


def _infer_target_from_id(value: str, *, tag: str, review_tag: str) -> dict[str, Any]:
    normalized = value.strip()
    if not normalized:
        return {"kind": DEFAULT_TARGET_KIND, "adhoc-id": normalized}
    if ":" in normalized:
        return _parse_target(normalized, adhoc_requested=False)
    if normalized.startswith("PKT-"):
        return {"kind": "packet", "packet-id": normalized}
    if normalized.startswith("job_") or normalized.startswith("job-") or normalized.startswith("job"):
        return {"kind": "job", "job-id": normalized}
    if "/" in normalized or "\\" in normalized or normalized.endswith(".md") or normalized.endswith(".json"):
        return {"kind": "artifact", "artifact-path": normalized}
    if tag == review_tag:
        return {"kind": "job", "job-id": normalized}
    return {"kind": DEFAULT_TARGET_KIND, "adhoc-id": normalized}
