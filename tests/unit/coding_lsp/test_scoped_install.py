from __future__ import annotations

import asyncio
from pathlib import Path

from audiagentic.components.optional.coding_lsp import lsp_api
from audiagentic.components.optional.coding_lsp.coding_lsp_config import write_lsp_config


def _configure(tmp_path: Path, *languages: str) -> None:
    servers = {}
    for lang in languages:
        from audiagentic.components.optional.coding_lsp import language_registry
        spec = language_registry.get_language(lang)
        servers[lang] = language_registry.server_spec_dict(spec)
    write_lsp_config(tmp_path / ".coding-lsp" / "lsp.json", servers)


def test_configured_dependency_ids_only_enabled(tmp_path: Path) -> None:
    _configure(tmp_path, "python")
    assert lsp_api.configured_dependency_ids(tmp_path) == ["pyright"]


def test_install_rejects_non_enabled_dependency(tmp_path: Path) -> None:
    _configure(tmp_path, "python")

    async def _never(**_kw):  # run_with_output must not be reached
        raise AssertionError("install should be rejected before running")

    result = asyncio.run(
        lsp_api.install_lsp_dependencies(["clangd"], run_with_output=_never, root=str(tmp_path))
    )
    assert result["ok"] is False
    assert "clangd" in result["error"]


def test_install_empty_skips_when_nothing_missing(tmp_path: Path, monkeypatch) -> None:
    _configure(tmp_path, "python")
    monkeypatch.setattr(lsp_api, "missing_configured_dependencies", lambda root: [])

    async def _never(**_kw):
        raise AssertionError("nothing to install")

    result = asyncio.run(
        lsp_api.install_lsp_dependencies([], run_with_output=_never, root=str(tmp_path))
    )
    assert result["ok"] is True
    assert result["installed"] == []


def test_install_empty_targets_configured_missing(tmp_path: Path, monkeypatch) -> None:
    _configure(tmp_path, "python")
    monkeypatch.setattr(lsp_api, "missing_configured_dependencies", lambda root: ["pyright"])
    captured: dict[str, object] = {}

    async def _capture(*, ctx, logger, heartbeat_message, work):
        captured["ran"] = True
        return {"ok": True}

    result = asyncio.run(
        lsp_api.install_lsp_dependencies([], run_with_output=_capture, root=str(tmp_path))
    )
    assert result == {"ok": True}
    assert captured["ran"] is True
