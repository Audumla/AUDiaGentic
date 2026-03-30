from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.lifecycle.detector import detect_installed_state


def test_detect_none(tmp_path: Path) -> None:
    state = detect_installed_state(tmp_path)
    assert state.state == "none"


def test_detect_legacy_only(tmp_path: Path) -> None:
    legacy = tmp_path / ".github" / "workflows"
    legacy.mkdir(parents=True)
    (legacy / "release-please.yml").write_text("legacy", encoding="utf-8")
    state = detect_installed_state(tmp_path)
    assert state.state == "legacy-only"


def test_detect_audiagentic_current(tmp_path: Path) -> None:
    audi_root = tmp_path / ".audiagentic"
    audi_root.mkdir()
    (audi_root / "installed.json").write_text("{}", encoding="utf-8")
    (audi_root / "project.yaml").write_text("contract-version: v1", encoding="utf-8")
    state = detect_installed_state(tmp_path)
    assert state.state == "audiagentic-current"


def test_detect_mixed_or_invalid(tmp_path: Path) -> None:
    audi_root = tmp_path / ".audiagentic"
    audi_root.mkdir()
    (audi_root / "installed.json").write_text("{}", encoding="utf-8")
    (audi_root / "project.yaml").write_text("contract-version: v1", encoding="utf-8")
    legacy = tmp_path / ".github" / "workflows"
    legacy.mkdir(parents=True)
    (legacy / "release-please.yml").write_text("legacy", encoding="utf-8")
    state = detect_installed_state(tmp_path)
    assert state.state == "mixed-or-invalid"


def test_missing_root_raises() -> None:
    missing = Path("does-not-exist-root")
    try:
        detect_installed_state(missing)
    except FileNotFoundError:
        assert True
    else:
        raise AssertionError("expected FileNotFoundError")
