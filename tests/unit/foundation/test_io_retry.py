from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.io import load_yaml_file, read_text_with_retry, save_yaml_file


def test_load_yaml_file_rejects_duplicate_top_level_key(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text("name: first\nname: second\n", encoding="utf-8")

    with pytest.raises(Exception, match="Invalid YAML config"):
        load_yaml_file(path)


def test_load_yaml_file_rejects_duplicate_nested_key(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text("settings:\n  mode: first\n  mode: second\n", encoding="utf-8")

    with pytest.raises(Exception, match="Invalid YAML config"):
        load_yaml_file(path)


def test_load_yaml_file_accepts_unique_mapping(tmp_path: Path) -> None:
    path = tmp_path / "unique.yaml"
    path.write_text("name: example\nsettings:\n  mode: safe\n", encoding="utf-8")

    assert load_yaml_file(path) == {"name": "example", "settings": {"mode": "safe"}}


def test_save_then_load_yaml_file_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "round-trip.yaml"
    payload = {"name": "example", "items": ["one", "two"]}

    save_yaml_file(path, payload)

    assert load_yaml_file(path) == payload


def test_read_text_retries_a_transient_sharing_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "record.json"
    path.write_text("ready", encoding="utf-8")
    original = Path.read_text
    calls = 0

    def transient(target: Path, *args, **kwargs) -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise PermissionError("sharing violation")
        return original(target, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", transient)

    assert read_text_with_retry(path) == "ready"
    assert calls == 3


def test_read_text_does_not_hide_a_persistent_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "record.json"
    path.write_text("ready", encoding="utf-8")
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("denied")),
    )

    with pytest.raises(PermissionError, match="denied"):
        read_text_with_retry(path)
