from __future__ import annotations

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
        [
            sys.executable,
            "-m",
            "audiagentic.components.providers.validate_ids",
            str(tmp_path),
        ],
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
            [sys.executable, "-m", "audiagentic.foundation.contracts.validate_schemas"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
    finally:
        bad_fixture.write_text(backup, encoding="utf-8")

