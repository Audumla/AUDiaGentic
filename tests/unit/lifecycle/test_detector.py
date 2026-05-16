from __future__ import annotations

from pathlib import Path

from audiagentic.runtime.lifecycle.detector import detect_installed_state


def test_detect_none(tmp_path: Path) -> None:
    state = detect_installed_state(tmp_path)
    assert state.state == "none"


def test_detect_installed(tmp_path: Path) -> None:
    audi_root = tmp_path / ".audiagentic"
    (audi_root / "components").mkdir(parents=True)
    (audi_root / "components" / "core-lifecycle.yaml").write_text(
        "component-id: core-lifecycle\nenabled: true\n", encoding="utf-8"
    )
    state = detect_installed_state(tmp_path)
    assert state.state == "installed"


def test_detect_invalid_partial_install(tmp_path: Path) -> None:
    audi_root = tmp_path / ".audiagentic"
    audi_root.mkdir(parents=True)
    # .audiagentic exists but core-lifecycle marker is absent
    state = detect_installed_state(tmp_path)
    assert state.state == "invalid"


def test_missing_root_raises() -> None:
    missing = Path("does-not-exist-root")
    try:
        detect_installed_state(missing)
    except FileNotFoundError:
        assert True
    else:
        raise AssertionError("expected FileNotFoundError")
