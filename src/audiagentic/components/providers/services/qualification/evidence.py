"""Native surface qualification evidence: one schema, one store (SH53).

A record states what was proven about one installed implementation of one
provider session surface on one platform. It is generated state, never
configuration, and never by itself authority to execute. The same records
serve SH46 joined-surface resolution and CFG07 ``audiagentic qualify``.

Records are immutable and append-only, written atomically under
``<state>/providers/qualification/v1/<provider-id>/<evidence-id>.json``. The
evidence id is a digest of the record's content, so re-publishing the same
result is a no-op and a new binary or adapter always yields a new record.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.contracts.schema_registry import read_schema
from audiagentic.foundation.paths.home import user_state_dir

evidence_error = make_error_factory("VAL", "QEV", "providers")

SCHEMA_STEM = "qualification-evidence"
LAYOUT_VERSION = "v1"


def evidence_root(state_root: Path | None = None) -> Path:
    """Where records live: the user state dir unless a server state root is given."""
    return (state_root or user_state_dir()) / "providers" / "qualification" / LAYOUT_VERSION


def _validator() -> Draft202012Validator:
    return Draft202012Validator(read_schema(SCHEMA_STEM))


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def file_digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            sha.update(chunk)
    return "sha256:" + sha.hexdigest()


def build_record(*, producer: dict[str, Any], target: dict[str, Any], qualification: dict[str, Any],
                 proof: dict[str, Any], created_at: datetime | None = None) -> dict[str, Any]:
    """A validated record whose id is derived from its content."""
    body = {"schema-version": 1, "producer": producer, "target": target,
            "qualification": qualification, "proof": proof}
    record = {
        **body,
        "evidence-id": "qe_" + hashlib.sha256(_canonical(body)).hexdigest()[:24],
        "created-at": (created_at or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z"),
    }
    validate_record(record)
    return record


def validate_record(record: Any) -> None:
    errors = sorted(_validator().iter_errors(record), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        raise evidence_error(1, f"Invalid qualification evidence: {first.message}",
                             pointer="/" + "/".join(str(part) for part in first.absolute_path), issues=len(errors))
    if record["qualification"]["state"] == "supported" and not any(record["qualification"]["capabilities"].values()):
        raise evidence_error(2, "A supported result must prove at least one capability")


def write_evidence(record: dict[str, Any], *, state_root: Path | None = None) -> Path:
    """Publish one record atomically. Existing records are never rewritten."""
    validate_record(record)
    directory = evidence_root(state_root) / record["target"]["provider-id"]
    path = directory / f"{record['evidence-id']}.json"
    if path.exists():
        return path
    directory.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("wb", dir=directory, prefix=".tmp-", suffix=".json", delete=False)
    try:
        with handle:
            handle.write(_canonical(record))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise
    return path


@dataclass(frozen=True)
class EvidenceRead:
    records: tuple[dict[str, Any], ...]
    rejected: tuple[tuple[Path, str], ...]  # unreadable or invalid files, never used


def read_evidence(provider_id: str, *, state_root: Path | None = None) -> EvidenceRead:
    directory = evidence_root(state_root) / provider_id
    records, rejected = [], []
    for path in sorted(directory.glob("qe_*.json")) if directory.is_dir() else ():
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            validate_record(record)
            if path.stem != record["evidence-id"] or record["target"]["provider-id"] != provider_id:
                raise ValueError("record does not match its location")
        except Exception as error:  # noqa: BLE001 - corrupt evidence fails closed
            rejected.append((path, str(error)))
            continue
        records.append(record)
    return EvidenceRead(tuple(records), tuple(rejected))


def find_exact(*, provider_id: str, surface_id: str, platform: str, executable_digest: str,
               adapter_digest: str, native_schema_version: str,
               state_root: Path | None = None) -> dict[str, Any] | None:
    """The newest record for this exact implementation identity, if any.

    Every identity field must match; a version string alone never does.
    """
    matches = [
        record for record in read_evidence(provider_id, state_root=state_root).records
        if record["target"]["surface-id"] == surface_id
        and record["target"]["platform"] == platform
        and record["target"]["executable-digest"] == executable_digest
        and record["producer"]["adapter-digest"] == adapter_digest
        and record["target"]["native-schema-version"] == native_schema_version
    ]
    return max(matches, key=lambda record: record["created-at"]) if matches else None


def proven_capabilities(record: dict[str, Any] | None) -> frozenset[str]:
    """Capabilities a record actually proves; nothing for unsupported or missing evidence."""
    if record is None or record["qualification"]["state"] not in {"supported", "partial"}:
        return frozenset()
    return frozenset(name for name, proven in record["qualification"]["capabilities"].items() if proven)


def inventory(provider_id: str) -> dict[str, Any]:
    """Read-only facts about the installed implementation of a provider.

    Executable path, exact version, content digest and platform triple. No
    process other than the descriptor's own version probe is run, and nothing
    is written. Missing pieces are reported as None, never guessed.
    """
    from audiagentic.components.providers.descriptors import all_descriptors
    from audiagentic.components.providers.services.lifecycle.lifecycle import probe_provider_cli
    from audiagentic.runtime.system.platform import release_platform_name

    descriptor = all_descriptors().get(provider_id)
    if descriptor is None:
        raise evidence_error(3, "Unknown provider", provider=provider_id)
    facts: dict[str, Any] = {
        "provider-id": provider_id,
        "platform": release_platform_name(),
        "surfaces": [surface.surface_id for surface in descriptor.session_surfaces],
        "executable": None, "executable-version": None, "executable-digest": None,
    }
    # The same probe startup reconcile uses: the descriptor's cli_probe or its
    # install recipe's own probe.
    probe = probe_provider_cli(descriptor)
    if not probe or not probe.get("available"):
        return facts
    located = probe.get("executable") or (shutil.which(probe["command"][0]) if probe.get("command") else None)
    if located:
        executable = Path(located).resolve()
        facts["executable"] = str(executable)
        # For wrapper launchers (for example a node script) this digests the
        # wrapper, not a native binary it spawns; qualification producers must
        # bind the actual native implementation where one exists.
        facts["executable-digest"] = file_digest(executable)
    facts["executable-version"] = extract_version(probe.get("stdout", "") or "")
    return facts


_VERSION_TOKEN = re.compile(r"(?<![\w.])v?(\d+(?:\.\d+){1,3})(?![\w.])")


def extract_version(output: str) -> str | None:
    """First version-shaped token in a CLI's version output.

    CLIs prefix their name ("codex-cli 0.165.0", "opencode v2.2.0"), which the
    surface resolver's start-anchored parser does not accept; inventory needs
    the exact version regardless.
    """
    match = _VERSION_TOKEN.search(output)
    return match.group(1) if match else None
