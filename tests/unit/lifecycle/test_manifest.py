from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.lifecycle.checkpoints import write_checkpoint
from audiagentic.lifecycle.manifest import (
    build_manifest,
    read_manifest,
    validate_manifest,
    write_manifest,
)

SCHEMA = ROOT / "docs" / "schemas" / "installed-state.schema.json"


def test_manifest_roundtrip(tmp_path: Path) -> None:
    payload = build_manifest(
        installation_kind="fresh",
        current_version="0.1.0",
        previous_version=None,
        components={"core-lifecycle": "installed"},
        providers={"local-openai": "configured"},
        last_lifecycle_action="fresh-install",
    )
    write_manifest(tmp_path, payload)
    result = read_manifest(tmp_path)
    assert result.installation_kind == "fresh"
    assert result.current_version == "0.1.0"


def test_manifest_validation_errors() -> None:
    payload = {"contract-version": "v1"}
    issues = validate_manifest(payload)
    assert issues


def test_manifest_invalid_read_raises(tmp_path: Path) -> None:
    target = tmp_path / ".audiagentic"
    target.mkdir()
    (target / "installed.json").write_text("{bad", encoding="utf-8")
    try:
        read_manifest(tmp_path)
    except AudiaGenticError as exc:
        assert exc.kind == "validation"
    else:
        raise AssertionError("expected validation error")


def test_manifest_fixtures_validate() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    fixtures = ROOT / "docs" / "examples" / "fixtures"
    for name in ("installed-state.fresh.valid.json", "installed-state.cutover.valid.json"):
        payload = json.loads((fixtures / name).read_text(encoding="utf-8"))
        errors = list(validator.iter_errors(payload))
        assert not errors
    invalid = json.loads((fixtures / "installed-state.invalid.json").read_text(encoding="utf-8"))
    errors = list(validator.iter_errors(invalid))
    assert errors


def test_checkpoint_writer_deterministic(tmp_path: Path) -> None:
    checkpoint = write_checkpoint(
        tmp_path,
        "planned",
        {"status": "ok"},
        timestamp="2026-03-29T00:00:00Z",
    )
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["phase"] == "planned"
    assert payload["timestamp"] == "2026-03-29T00:00:00Z"
    assert payload["payload"] == {"status": "ok"}
