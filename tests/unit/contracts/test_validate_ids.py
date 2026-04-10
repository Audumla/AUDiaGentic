from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.validation.validate_ids as validate_ids


def _write_yaml(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_validate_ids_ok(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "config.yaml",
        """
contract-version: v1
providers:
  local-openai:
    enabled: true
components:
  core-lifecycle:
    enabled: true
""".lstrip(),
    )
    findings = validate_ids.scan_paths([tmp_path])
    assert findings == []


def test_validate_ids_rejects_invalid(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "bad.yaml",
        """
contract-version: v1
providers:
  local_openai:
    enabled: true
components:
  core_lifecycle:
    enabled: true
""".lstrip(),
    )
    findings = validate_ids.scan_paths([tmp_path])
    assert findings
    issues = " ".join(entry["issue"] for entry in findings)
    assert "invalid ids" in issues


def test_validate_ids_ignores_invalid_fixtures(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "provider-config.invalid.yaml",
        """
contract-version: v1
providers:
  local_openai:
    enabled: true
components:
  core_lifecycle:
    enabled: true
""".lstrip(),
    )
    findings = validate_ids.scan_paths([tmp_path])
    assert findings == []


def test_validate_ids_ignores_schema_contents(tmp_path: Path, monkeypatch) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    schema_dir = tmp_path / "src" / "audiagentic" / "contracts" / "schemas"
    schema_dir.mkdir(parents=True)
    (schema_dir / "provider-config.schema.json").write_text(
        """
{
  "type": "object",
  "properties": {
    "type": {"const": "provider-config"},
    "additionalProperties": false,
    "required": ["providers"]
  }
}
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(validate_ids, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(validate_ids, "SCHEMA_DIR", schema_dir)
    monkeypatch.setattr(validate_ids, "validate_schema_files", lambda _path: [])
    findings = validate_ids.scan_paths([docs_root])
    assert findings == []
