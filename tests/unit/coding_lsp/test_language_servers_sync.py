from __future__ import annotations

from pathlib import Path

from audiagentic.components.optional.coding_lsp.coding_lsp_config import write_lsp_config
from audiagentic.components.optional.coding_lsp.language_servers_sync import (
    prune_language_servers_from_providers,
    sync_language_servers_to_providers,
)
from audiagentic.components.optional.providers.descriptors.base import (
    LanguageServersConfigSpec,
)


class _Descriptor:
    def __init__(self, provider_id: str, spec: LanguageServersConfigSpec | None) -> None:
        self.provider_id = provider_id
        self.language_servers_config = spec


def _spec(writer, *, reader=lambda path: {}, remover=lambda path, lang: False) -> LanguageServersConfigSpec:
    return LanguageServersConfigSpec(
        config_path=".codex/config.toml",
        reader=reader,
        writer=writer,
        remover=remover,
        format="test",
    )


def test_sync_skips_when_config_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "audiagentic.components.optional.coding_lsp.language_servers_sync.all_descriptors",
        lambda: {},
    )
    result = sync_language_servers_to_providers(tmp_path)
    assert result["synced"] == []
    assert result["skipped"] == "no valid configured language servers"


def test_sync_writes_real_entries(tmp_path: Path, monkeypatch) -> None:
    write_lsp_config(tmp_path / ".coding-lsp" / "lsp.json", {
        "python": {
            "command": ["pyright-langserver", "--stdio"],
            "fileExtensions": [".py", ".pyi"],
            "settings": {"python": {"analysis": "basic"}},
        }
    })
    written: dict[str, object] = {}

    def _writer(path: Path, entries) -> None:
        written["path"] = path
        written["entries"] = entries

    monkeypatch.setattr(
        "audiagentic.components.optional.coding_lsp.language_servers_sync.all_descriptors",
        lambda: {"codex": _Descriptor("codex", _spec(_writer))},
    )

    result = sync_language_servers_to_providers(tmp_path)

    assert result["synced"] == ["codex"]
    entries = written["entries"]
    assert entries["python"].command == ["pyright-langserver", "--stdio"]
    assert entries["python"].file_extensions == [".py", ".pyi"]


def test_prune_removes_configured_languages(tmp_path: Path, monkeypatch) -> None:
    # lsp.json names which languages were synced — prune removes exactly those.
    write_lsp_config(tmp_path / ".coding-lsp" / "lsp.json", {
        "python": {"command": ["pyright-langserver", "--stdio"], "fileExtensions": [".py"]},
    })
    removed: list[str] = []

    def _remover(path: Path, language: str) -> bool:
        removed.append(language)
        return True

    monkeypatch.setattr(
        "audiagentic.components.optional.coding_lsp.language_servers_sync.all_descriptors",
        lambda: {"codex": _Descriptor("codex", _spec(lambda p, e: None, remover=_remover))},
    )

    result = prune_language_servers_from_providers(tmp_path)

    assert result["pruned"] == ["codex"]
    assert removed == ["python"]
    assert result["details"]["codex"]["removed"] == ["python"]


def test_prune_noop_when_no_config(tmp_path: Path, monkeypatch) -> None:
    removed: list[str] = []
    monkeypatch.setattr(
        "audiagentic.components.optional.coding_lsp.language_servers_sync.all_descriptors",
        lambda: {"codex": _Descriptor("codex", _spec(lambda p, e: None, remover=lambda p, l: removed.append(l) or True))},
    )
    result = prune_language_servers_from_providers(tmp_path)
    assert result["languages"] == []
    assert removed == []
