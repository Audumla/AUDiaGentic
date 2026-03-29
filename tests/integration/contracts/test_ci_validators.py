from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = ROOT / "docs" / "examples" / "fixtures"


def test_validate_ids_fails_on_bad_fixture(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
contract-version: v1
providers:
  not-a-provider:
    enabled: true
    install-mode: external-configured
""".lstrip(),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "tools/validate_ids.py", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2


def test_validate_schemas_fails_on_bad_fixture() -> None:
    bad_fixture = FIXTURES_DIR / "project-config.valid.json"
    backup = bad_fixture.read_text(encoding="utf-8")
    try:
        bad_fixture.write_text("{\"contract-version\": \"v1\"}", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "tools/validate_schemas.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
    finally:
        bad_fixture.write_text(backup, encoding="utf-8")


def test_validate_packet_dependencies_fails_on_unknown_dependency(tmp_path: Path) -> None:
    registry = tmp_path / "registry.md"
    registry.write_text(
        """
| Packet | Title | Status | Owner | Branch/Worktree | Dependency State | Primary Docs | Last Update | Notes |
|---|---|---|---|---|---|---|---|---|
| PKT-FND-001 | Canonical IDs | READY_TO_START | - | - | none | 03 | 2026-03-29 | |
| PKT-FND-002 | Schema package | WAITING_ON_DEPENDENCIES | - | - | needs PKT-XYZ-999 VERIFIED | 03 | 2026-03-29 | |
""".strip(),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "tools/validate_packet_dependencies.py",
            "--registry",
            str(registry),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
