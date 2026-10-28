"""SH53: one qualification evidence schema and an append-only store."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from audiagentic.components.providers.services.qualification import evidence
from audiagentic.foundation.contracts.errors import AudiaGenticError

DIGEST = "sha256:" + "a" * 64


def _record(**changes) -> dict:
    target = {"provider-id": "codex", "surface-id": "codex-acp", "platform": "linux-amd64",
              "executable-version": "0.165.0", "executable-digest": DIGEST, "native-protocol": "acp",
              "native-schema-version": "1", "endpoint-kind": "stdio", **changes.pop("target", {})}
    qualification = {"state": "partial", "capabilities": {"passive-identity": True, "safe-detach": False},
                     "unsupported-reasons": ["existing-session-attach-unproven"], **changes.pop("qualification", {})}
    return evidence.build_record(
        producer={"component": "providers", "qualifier-version": "1", "suite-digest": DIGEST,
                  "adapter-id": "codex-acp", "adapter-version": "1", "adapter-digest": DIGEST,
                  **changes.pop("producer", {})},
        target=target, qualification=qualification,
        proof={"fixture-id": "disposable-codex", "test-run-id": "run-1", "artifact-digest": DIGEST,
               "verified-at": "2026-10-28T00:00:00Z"},
        created_at=changes.pop("created_at", datetime(2026, 10, 28, tzinfo=timezone.utc)),
    )


def test_evidence_id_is_derived_from_content() -> None:
    first, again = _record(), _record(created_at=datetime(2026, 10, 29, tzinfo=timezone.utc))
    assert first["evidence-id"] == again["evidence-id"]  # same proof, same id
    assert _record(target={"executable-digest": "sha256:" + "b" * 64})["evidence-id"] != first["evidence-id"]


def test_schema_requires_implementation_identity() -> None:
    record = _record()
    del record["target"]["executable-digest"]
    with pytest.raises(AudiaGenticError) as raised:
        evidence.validate_record(record)
    assert raised.value.code == "VAL-QEV-001"


def test_supported_requires_a_proven_capability() -> None:
    with pytest.raises(AudiaGenticError) as raised:
        _record(qualification={"state": "supported", "capabilities": {"passive-identity": False}})
    assert raised.value.code == "VAL-QEV-002"


def test_write_is_atomic_and_append_only(tmp_path: Path) -> None:
    record = _record()
    path = evidence.write_evidence(record, state_root=tmp_path)
    assert path == tmp_path / "providers" / "qualification" / "v1" / "codex" / f"{record['evidence-id']}.json"
    before = path.read_bytes()
    assert evidence.write_evidence(record, state_root=tmp_path) == path
    assert path.read_bytes() == before
    assert [p.name for p in path.parent.iterdir()] == [path.name]  # no temp files left


def test_corrupt_or_misplaced_records_fail_closed(tmp_path: Path) -> None:
    good = _record()
    evidence.write_evidence(good, state_root=tmp_path)
    directory = evidence.evidence_root(tmp_path) / "codex"
    (directory / "qe_000000000000000000000000.json").write_text("{not json", encoding="utf-8")
    other = _record(target={"provider-id": "pi"})
    (directory / f"{other['evidence-id']}.json").write_text(json.dumps(other), encoding="utf-8")
    read = evidence.read_evidence("codex", state_root=tmp_path)
    assert [record["evidence-id"] for record in read.records] == [good["evidence-id"]]
    assert len(read.rejected) == 2


def test_find_exact_needs_every_identity_field(tmp_path: Path) -> None:
    older = _record(created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                    qualification={"unsupported-reasons": ["older-run"]})
    newer = _record()
    for record in (older, newer):
        evidence.write_evidence(record, state_root=tmp_path)
    exact = dict(provider_id="codex", surface_id="codex-acp", platform="linux-amd64", executable_digest=DIGEST,
                 adapter_digest=DIGEST, native_schema_version="1", state_root=tmp_path)
    assert evidence.find_exact(**exact)["evidence-id"] == newer["evidence-id"]
    for field, value in (("platform", "windows-amd64"), ("executable_digest", "sha256:" + "c" * 64),
                         ("adapter_digest", "sha256:" + "d" * 64), ("native_schema_version", "2"),
                         ("surface_id", "codex-app-server")):
        assert evidence.find_exact(**{**exact, field: value}) is None


def test_only_proven_capabilities_count() -> None:
    assert evidence.proven_capabilities(None) == frozenset()
    assert evidence.proven_capabilities(_record()) == {"passive-identity"}
    unsupported = _record(qualification={"state": "unsupported", "capabilities": {"passive-identity": True}})
    assert evidence.proven_capabilities(unsupported) == frozenset()


@pytest.mark.parametrize(
    ("output", "expected"),
    [("pi 1.4.0", "1.4.0"), ("opencode v2.2.0", "2.2.0"), ("codex-cli 0.165.0", "0.165.0"),
     ("2.1.312 (Claude Code)", "2.1.312"), ("no version here", None), ("build 20260101", None)],
)
def test_extract_version(output: str, expected: str | None) -> None:
    assert evidence.extract_version(output) == expected


def test_inventory_reports_identity_without_guessing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from audiagentic.components.providers.services.lifecycle import lifecycle

    binary = tmp_path / "codex"
    binary.write_bytes(b"#!/bin/sh\necho codex-cli 0.165.0\n")
    monkeypatch.setattr(lifecycle, "probe_provider_cli",
                        lambda descriptor: {"available": True, "executable": str(binary),
                                            "command": ["codex", "--version"], "stdout": "codex-cli 0.165.0\n"})
    facts = evidence.inventory("codex")
    assert facts["executable"] == str(binary.resolve())
    assert facts["executable-version"] == "0.165.0"
    assert facts["executable-digest"] == evidence.file_digest(binary)
    assert "codex-acp" in facts["surfaces"]

    monkeypatch.setattr(lifecycle, "probe_provider_cli", lambda descriptor: {"available": False})
    missing = evidence.inventory("codex")
    assert missing["executable"] is None and missing["executable-digest"] is None
    with pytest.raises(AudiaGenticError) as raised:
        evidence.inventory("no-such-provider")
    assert raised.value.code == "VAL-QEV-003"
