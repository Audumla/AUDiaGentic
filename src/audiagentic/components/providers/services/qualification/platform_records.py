"""Local platform qualification records (CFG07).

A provider descriptor ships vendor evidence for the platforms the vendor
tested. Everything else is ``unqualified`` until the user runs
``audiagentic qualify``, which proves the installed implementation on this
machine and writes one record per provider, surface and platform:

``<state>/qualification/v1/<provider>/<surface>/<platform>.yaml``

A record binds the implementation fingerprint (executable digest, adapter
reference), the package version, the qualification spec version, the result,
the time, the environment and the digest of the retained evidence. The surface
resolver accepts a record only when every bound fact still matches; a stale or
foreign record is rejected, and one platform's record never stands in for
another's. Missing evidence is ``unqualified``, never a failure.

Generated state, never configuration. The richer native-attach evidence of SH53
(``evidence.py``) is a separate, finer-grained record kept as is.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from audiagentic.foundation.io import atomic_write_text
from audiagentic.foundation.paths.home import user_state_dir

LAYOUT_VERSION = "v1"
SPEC_VERSION = 1
RESULTS = ("qualified", "failed")
_REQUIRED = (
    "provider-id", "surface-id", "platform", "fingerprint", "package-version",
    "spec-version", "result", "qualified-at", "environment", "evidence-digest",
)


def records_root(state_root: Path | None = None) -> Path:
    return (state_root or user_state_dir()) / "qualification" / LAYOUT_VERSION


def record_path(provider_id: str, surface_id: str, platform: str, state_root: Path | None = None) -> Path:
    for part in (provider_id, surface_id, platform):
        if not part or "/" in part or "\\" in part or part.startswith("."):
            raise ValueError(f"unsafe qualification path component: {part!r}")
    return records_root(state_root) / provider_id / surface_id / f"{platform}.yaml"


def package_version() -> str:
    from audiagentic import __version__

    return __version__


def environment() -> dict[str, str]:
    return {"python": ".".join(str(part) for part in sys.version_info[:3]), "os": sys.platform}


def evidence_digest(checks: list[dict[str, Any]]) -> str:
    blob = json.dumps(checks, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def current_fingerprint(provider_id: str, adapter_ref: str | None) -> dict[str, Any]:
    """Facts that identify the installed implementation; None when a fact does not apply."""
    from .evidence import inventory

    facts = inventory(provider_id)
    return {
        "executable-digest": facts.get("executable-digest"),
        "executable-version": facts.get("executable-version"),
        "adapter-ref": adapter_ref,
    }


def build_record(
    *, provider_id: str, surface_id: str, platform: str, fingerprint: dict[str, Any],
    checks: list[dict[str, Any]], now: datetime | None = None,
) -> dict[str, Any]:
    passed = bool(checks) and all(check["ok"] for check in checks)
    return {
        "provider-id": provider_id,
        "surface-id": surface_id,
        "platform": platform,
        "fingerprint": fingerprint,
        "package-version": package_version(),
        "spec-version": SPEC_VERSION,
        "result": "qualified" if passed else "failed",
        "qualified-at": (now or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
        "environment": environment(),
        "evidence-digest": evidence_digest(checks),
        "checks": checks,
    }


def write_record(record: dict[str, Any], state_root: Path | None = None) -> Path:
    """Publish one record atomically, replacing the previous one for the same platform."""
    path = record_path(record["provider-id"], record["surface-id"], record["platform"], state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, yaml.safe_dump(record, sort_keys=False))
    return path


@dataclass(frozen=True)
class RecordStatus:
    """The usable record for one platform, or the reason there is none."""

    record: dict[str, Any] | None
    reason: str  # "" when usable; "unqualified", "invalid", "failed" or "stale"
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.record is not None and not self.reason


def check_record(
    provider_id: str, surface_id: str, platform: str, *,
    adapter_ref: str | None = None, state_root: Path | None = None, fingerprint: dict[str, Any] | None = None,
) -> RecordStatus:
    """Judge the local record for exactly this provider, surface and platform.

    ``fingerprint`` is the current implementation fingerprint; it is measured
    only when a record exists, so an unqualified surface costs one stat.
    """
    path = record_path(provider_id, surface_id, platform, state_root)
    if not path.is_file():
        return RecordStatus(None, "unqualified")
    try:
        record = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict) or any(key not in record for key in _REQUIRED):
            raise ValueError("missing required fields")
        if (record["provider-id"], record["surface-id"], record["platform"]) != (provider_id, surface_id, platform):
            raise ValueError("record does not match its location")
        if record["result"] not in RESULTS:
            raise ValueError("unknown result")
    except Exception as error:  # noqa: BLE001 - unreadable evidence fails closed
        return RecordStatus(None, "invalid", str(error))
    if record["result"] != "qualified":
        return RecordStatus(record, "failed")
    if record["spec-version"] != SPEC_VERSION:
        return RecordStatus(record, "stale", "qualification spec changed")
    if record["package-version"] != package_version():
        return RecordStatus(record, "stale", "package version changed")
    now = fingerprint if fingerprint is not None else current_fingerprint(provider_id, adapter_ref)
    for key, held in record["fingerprint"].items():
        if held != now.get(key) and key != "executable-version":
            return RecordStatus(record, "stale", f"{key} changed")
    return RecordStatus(record, "")
