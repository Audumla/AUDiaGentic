from __future__ import annotations

import asyncio
from pathlib import Path

from audiagentic.components.optional.coding_lsp import lsp_api
from audiagentic.components.optional.coding_lsp import lsp_config_api
from audiagentic.components.optional.coding_lsp.coding_lsp_config import read_lsp_config, write_lsp_config


def _configure(tmp_path: Path, *languages: str) -> None:
    servers = {}
    for lang in languages:
        from audiagentic.components.optional.coding_lsp import language_registry
        spec = language_registry.get_language(lang)
        servers[lang] = language_registry.server_spec_dict(spec)
    write_lsp_config(tmp_path / ".coding-lsp" / "lsp.json", servers)


def test_configured_dependency_ids_only_enabled(tmp_path: Path) -> None:
    _configure(tmp_path, "python")
    assert lsp_config_api.configured_dependency_ids(tmp_path) == ["pyright"]


def test_install_rejects_non_enabled_dependency(tmp_path: Path) -> None:
    _configure(tmp_path, "python")

    async def _never(**_kw):  # run_with_output must not be reached
        raise AssertionError("install should be rejected before running")

    result = asyncio.run(
        lsp_config_api.install_lsp_dependencies(["clangd"], run_with_output=_never, root=str(tmp_path))
    )
    assert result["ok"] is False
    assert "clangd" in result["error"]


def test_install_empty_skips_when_nothing_missing(tmp_path: Path, monkeypatch) -> None:
    _configure(tmp_path, "python")
    monkeypatch.setattr(lsp_config_api, "missing_configured_dependencies", lambda root: [])

    async def _never(**_kw):
        raise AssertionError("nothing to install")

    result = asyncio.run(
        lsp_config_api.install_lsp_dependencies([], run_with_output=_never, root=str(tmp_path))
    )
    assert result["ok"] is True
    assert result["installed"] == []


def test_install_empty_targets_configured_missing(tmp_path: Path, monkeypatch) -> None:
    _configure(tmp_path, "python")
    monkeypatch.setattr(lsp_config_api, "missing_configured_dependencies", lambda root: ["pyright"])
    captured: dict[str, object] = {}

    async def _capture(*, ctx, logger, heartbeat_message, work):
        captured["ran"] = True
        return {"ok": True}

    result = asyncio.run(
        lsp_config_api.install_lsp_dependencies([], run_with_output=_capture, root=str(tmp_path))
    )
    assert result == {"ok": True}
    assert captured["ran"] is True


def test_enable_language_installs_then_enables(tmp_path: Path, monkeypatch) -> None:
    # python's pyright server reports missing, install succeeds.
    _configure(tmp_path)  # anchor project root at tmp_path
    monkeypatch.setattr(lsp_config_api, "_sync_to_providers", lambda root: None)
    monkeypatch.setattr(lsp_config_api, "detect_missing", lambda probes, ids: list(ids))

    async def _ok(*_a, **_kw):
        return {"ok": True}

    monkeypatch.setattr(lsp_config_api, "install_lsp_dependencies", _ok)

    result = asyncio.run(
        lsp_config_api.enable_language(str(tmp_path), "python", run_with_output=_never)
    )
    assert result["ok"] is True
    assert result["installed"] == ["pyright"]
    assert "python" in read_lsp_config(tmp_path / ".coding-lsp" / "lsp.json")


def test_enable_language_rolls_back_on_install_failure(tmp_path: Path, monkeypatch) -> None:
    _configure(tmp_path)  # anchor project root at tmp_path
    monkeypatch.setattr(lsp_config_api, "_sync_to_providers", lambda root: None)
    monkeypatch.setattr(lsp_config_api, "detect_missing", lambda probes, ids: list(ids))

    async def _fail(*_a, **_kw):
        return {"ok": False, "error": "boom"}

    monkeypatch.setattr(lsp_config_api, "install_lsp_dependencies", _fail)

    result = asyncio.run(
        lsp_config_api.enable_language(str(tmp_path), "python", run_with_output=_never)
    )
    assert result["ok"] is False
    assert result["rolled_back"] is True
    assert "python" not in read_lsp_config(tmp_path / ".coding-lsp" / "lsp.json")


async def _never(**_kw):
    raise AssertionError("run_with_output must not be called directly")
