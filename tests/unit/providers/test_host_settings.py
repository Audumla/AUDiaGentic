"""Host settings manifest merging (.vscode/settings.json and friends)."""
from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.providers.surfaces.host_settings import write_host_settings


def test_writes_new_settings_file(tmp_path: Path):
    path = write_host_settings(tmp_path, {"yaml.validate": True})
    assert path == tmp_path / ".vscode" / "settings.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"yaml.validate": True}


def test_preserves_unmanaged_keys(tmp_path: Path):
    settings_path = tmp_path / ".vscode" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps({"editor.tabSize": 4, "yaml.validate": False}), encoding="utf-8"
    )

    write_host_settings(tmp_path, {"yaml.validate": True, "yaml.completion": True})

    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data["editor.tabSize"] == 4
    assert data["yaml.validate"] is True
    assert data["yaml.completion"] is True


def test_idempotent_reapply(tmp_path: Path):
    write_host_settings(tmp_path, {"yaml.validate": True})
    path = write_host_settings(tmp_path, {"yaml.validate": True})
    assert json.loads(path.read_text(encoding="utf-8")) == {"yaml.validate": True}
