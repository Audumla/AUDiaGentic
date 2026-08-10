from __future__ import annotations

import asyncio
from pathlib import Path

from audiagentic.components.coding_lsp import lsp_config_api
from audiagentic.components.coding_lsp.coding_lsp_config import (
    get_coding_lsp_dir,
    read_lsp_config,
    write_lsp_config,
)
from audiagentic.foundation.features import registry as feature_registry
from audiagentic.foundation.features.base import (
    BindingDescriptor,
    FeatureState,
    ImplementationDescriptor,
    ImplementationState,
)
from audiagentic.foundation.features.state import (
    get_feature_state,
    set_feature_state,
    set_implementation_state,
)


def _register_language_binding(language: str) -> None:
    """Register a language binding (without enabling) so lsp.json regeneration resolves it."""
    feature_registry.register(
        BindingDescriptor(
            parent="coding-lsp",
            implementation="ag-lsp",
            feature_kind="language",
            feature=language,
            projection_writer_key="coding-lsp.lsp-json",
        )
    )


def _configure(tmp_path: Path, *languages: str) -> None:
    servers = {}
    for lang in languages:
        from audiagentic.components.coding_lsp import language_registry

        spec = language_registry.get_language(lang)
        if spec is not None:
            servers[lang] = language_registry.server_spec_dict(spec)
        feature_registry.register(
            BindingDescriptor(
                parent="coding-lsp",
                implementation="ag-lsp",
                feature_kind="language",
                feature=lang,
                projection_writer_key="coding-lsp.lsp-json",
            )
        )
        set_feature_state(
            tmp_path,
            "coding-lsp",
            "language",
            lang,
            FeatureState(enabled=True),
        )
    write_lsp_config(get_coding_lsp_dir(tmp_path) / "lsp.json", servers)


def test_configured_dependency_ids_only_enabled(tmp_path: Path) -> None:
    _configure(tmp_path, "python")
    assert lsp_config_api.configured_dependency_ids(tmp_path) == ["pyright"]


def test_install_rejects_non_enabled_dependency(tmp_path: Path) -> None:
    _configure(tmp_path, "python")

    result = asyncio.run(lsp_config_api.install_lsp_dependencies(["clangd"], root=str(tmp_path)))
    assert result["ok"] is False
    assert "clangd" in result["error"]


def test_install_empty_skips_when_nothing_missing(tmp_path: Path, monkeypatch) -> None:
    _configure(tmp_path, "python")
    monkeypatch.setattr(lsp_config_api, "missing_configured_dependencies", lambda root: [])

    result = asyncio.run(lsp_config_api.install_lsp_dependencies([], root=str(tmp_path)))
    assert result["ok"] is True
    assert result["installed"] == []


def test_install_empty_targets_configured_missing(tmp_path: Path, monkeypatch) -> None:
    _configure(tmp_path, "python")
    monkeypatch.setattr(lsp_config_api, "missing_configured_dependencies", lambda root: ["pyright"])

    result = asyncio.run(lsp_config_api.install_lsp_dependencies([], root=str(tmp_path)))
    assert result["status"] == "ok"


def test_install_accepts_active_implementation_dependency(tmp_path: Path) -> None:
    _configure(tmp_path, "python")
    feature_registry.register(
        ImplementationDescriptor(
            parent="coding-lsp",
            implementation_id="blackwell-agent-lsp",
            dependencies={
                "blackwell-agent-lsp": {
                    "probe": "binary:agent-lsp",
                    "toolchain": "npm",
                    "package": "@blackwell-systems/agent-lsp",
                },
            },
        )
    )
    set_implementation_state(
        tmp_path, "coding-lsp", "blackwell-agent-lsp", ImplementationState(enabled=True)
    )

    result = asyncio.run(
        lsp_config_api.install_lsp_dependencies(["blackwell-agent-lsp"], root=str(tmp_path))
    )

    assert result["status"] == "ok"


def test_enable_language_installs_then_enables(tmp_path: Path, monkeypatch) -> None:
    # python's pyright server reports missing, install succeeds.
    _configure(tmp_path)  # anchor project root at tmp_path
    _register_language_binding("python")  # binding present so lsp.json regenerates
    monkeypatch.setattr(lsp_config_api, "_sync_to_providers", lambda root: None)
    monkeypatch.setattr(lsp_config_api, "detect_missing", lambda probes, ids: list(ids))

    async def _ok(*_a, **_kw):
        return {"ok": True}

    monkeypatch.setattr(lsp_config_api, "install_lsp_dependencies", _ok)

    # Mock resolve_project_root to prevent walking up to a real .audiagentic directory
    monkeypatch.setattr(
        lsp_config_api,
        "resolve_project_root",
        lambda path: tmp_path,
    )

    result = asyncio.run(lsp_config_api.enable_language(str(tmp_path), "python"))
    assert result["ok"] is True
    assert result["installed"] == ["pyright"]
    # Regenerated cache reflects the resolved runtime server, not just the key.
    cache = read_lsp_config(get_coding_lsp_dir(tmp_path) / "lsp.json")
    assert cache["python"]["command"] == ["pyright-langserver", "--stdio"]
    assert get_feature_state(tmp_path, "coding-lsp", "language", "python").enabled is True


def test_enable_language_rolls_back_on_install_failure(tmp_path: Path, monkeypatch) -> None:
    _configure(tmp_path)  # anchor project root at tmp_path
    monkeypatch.setattr(lsp_config_api, "_sync_to_providers", lambda root: None)
    monkeypatch.setattr(lsp_config_api, "detect_missing", lambda probes, ids: list(ids))

    async def _fail(*_a, **_kw):
        return {"ok": False, "error": "boom"}

    monkeypatch.setattr(lsp_config_api, "install_lsp_dependencies", _fail)

    # Mock resolve_project_root to prevent walking up to a real .audiagentic directory
    monkeypatch.setattr(
        lsp_config_api,
        "resolve_project_root",
        lambda path: tmp_path,
    )

    result = asyncio.run(lsp_config_api.enable_language(str(tmp_path), "python"))
    assert result["ok"] is False
    assert result["rolled_back"] is True
    assert "python" not in read_lsp_config(get_coding_lsp_dir(tmp_path) / "lsp.json")
    assert get_feature_state(tmp_path, "coding-lsp", "language", "python").enabled is False


def test_remove_language_disables_feature_state(tmp_path: Path, monkeypatch) -> None:
    _configure(tmp_path, "python")
    monkeypatch.setattr(lsp_config_api, "_sync_to_providers", lambda root: None)
    lsp_config_api._set_language_feature_enabled(tmp_path, "python", True)

    result = lsp_config_api.remove_language(str(tmp_path), "python")

    assert result["ok"] is True
    assert get_feature_state(tmp_path, "coding-lsp", "language", "python").enabled is False
    # The cache is regenerated from feature state — the disabled language is gone.
    assert "python" not in read_lsp_config(get_coding_lsp_dir(tmp_path) / "lsp.json")


def test_language_option_projects_to_runtime_settings(tmp_path: Path, monkeypatch) -> None:
    _configure(tmp_path, "python")
    monkeypatch.setattr(lsp_config_api, "_sync_to_providers", lambda root: None)

    result = lsp_config_api.set_language_option(
        str(tmp_path),
        "python",
        "server-settings",
        {"python.analysis.typeCheckingMode": "strict"},
    )

    configured = read_lsp_config(get_coding_lsp_dir(tmp_path) / "lsp.json")
    assert result["ok"] is True
    assert configured["python"]["settings"] == {"python.analysis.typeCheckingMode": "strict"}
    assert get_feature_state(tmp_path, "coding-lsp", "language", "python").options[
        "server-settings"
    ] == {"python.analysis.typeCheckingMode": "strict"}


def test_reset_language_option_restores_base_runtime_settings(tmp_path: Path, monkeypatch) -> None:
    _configure(tmp_path, "python")
    monkeypatch.setattr(lsp_config_api, "_sync_to_providers", lambda root: None)
    lsp_config_api.set_language_option(
        str(tmp_path),
        "python",
        "server-settings",
        {"python.analysis.typeCheckingMode": "strict"},
    )

    result = lsp_config_api.reset_language_option(str(tmp_path), "python", "server-settings")

    configured = read_lsp_config(get_coding_lsp_dir(tmp_path) / "lsp.json")
    assert result["ok"] is True
    assert configured["python"]["settings"] == {}
    assert get_feature_state(tmp_path, "coding-lsp", "language", "python").options == {}


def test_language_option_rejects_unknown_option(tmp_path: Path) -> None:
    _configure(tmp_path, "python")

    result = lsp_config_api.set_language_option(str(tmp_path), "python", "missing", True)

    assert result["ok"] is False
    assert "unknown option" in result["error"]
