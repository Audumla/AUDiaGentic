"""Host adapter seam (AR09) — config-driven editor host abstraction."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.providers.services.host_adapter import (
    HostAdapter,
    all_host_adapters,
    get_host_adapter,
    register_host_adapter,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_vscode_host_loaded_from_config():
    adapter = get_host_adapter("vscode")
    assert adapter.workspace_marker == ".vscode"
    assert adapter.extensions_manifest == ".vscode/extensions.json"
    assert adapter.extension_dir().name == "extensions"


def test_unknown_host_raises():
    with pytest.raises(AudiaGenticError, match="CFG-HOST-001"):
        get_host_adapter("emacs")


def test_workspace_detection_and_manifest_path(tmp_path: Path):
    adapter = get_host_adapter("vscode")
    assert adapter.detect_workspace(tmp_path) is False
    (tmp_path / ".vscode").mkdir()
    assert adapter.detect_workspace(tmp_path) is True
    assert adapter.extensions_manifest_path(tmp_path) == tmp_path / ".vscode" / "extensions.json"


def test_second_host_is_config_only(tmp_path: Path):
    """Adding a host = one registry entry; every consumer path works unchanged."""
    fixture = HostAdapter(
        host_id="fixture-editor",
        workspace_marker=".fixture",
        extensions_manifest=".fixture/exts.json",
        extensions_dir=str(tmp_path / "ext-store"),
        display_name="Fixture Editor",
    )
    register_host_adapter(fixture)
    try:
        assert get_host_adapter("fixture-editor") is fixture
        assert "fixture-editor" in all_host_adapters()

        (tmp_path / ".fixture").mkdir()
        assert fixture.detect_workspace(tmp_path) is True

        # installed-extension probe against the configured dir
        ext_store = tmp_path / "ext-store"
        (ext_store / "pub.some-ext-1.0.0").mkdir(parents=True)
        assert fixture.installed_extension_ids() == ["pub.some-ext"]

        # manifest generation routes through the adapter
        from audiagentic.components.providers.descriptors.base import HostCapability
        from audiagentic.components.providers.surfaces.extensions_json import (
            write_extensions_json,
        )

        path = write_extensions_json(
            tmp_path,
            (HostCapability(host="fixture-editor", capability_id="pub.some-ext", display_name="X"),),
            host_id="fixture-editor",
        )
        assert path == tmp_path / ".fixture" / "exts.json"
        assert "pub.some-ext" in path.read_text(encoding="utf-8")
    finally:
        all_host_adapters()  # ensure loaded
        from audiagentic.components.providers.services import host_adapter as mod
        mod._registry.pop("fixture-editor", None)
