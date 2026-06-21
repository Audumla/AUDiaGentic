"""Per-provider adapter capability tests.

For every registered provider, exercise each capability its adapter actually
declares — driven by the descriptor's own specs, not a shared format helper — so a
provider that mis-wires its `mcp_config` / `language_servers_config` (wrong format
handler, missing remover, non-roundtripping writer) is caught.

These exercise the adapter config writers/readers/removers against a tmp project
root only (no host mutation, no CLI install), so they are host-safe. Real
CLI install/probe per provider is covered (dockerized, gated) by
`tests/integration/providers/test_provider_cli_comprehensive.py`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.optional.providers.descriptors.base import (
    LanguageServerEntry,
    ProviderDescriptor,
)
from audiagentic.components.optional.providers.descriptors.registry import all_descriptors
from audiagentic.foundation.mcp import McpServerEntry

_DESCRIPTORS = all_descriptors()
_MCP_PROVIDERS = sorted(pid for pid, d in _DESCRIPTORS.items() if d.mcp_config is not None)
_LS_PROVIDERS = sorted(pid for pid, d in _DESCRIPTORS.items() if d.language_servers_config is not None)


def _resolve_path(config_path, project_root: Path) -> Path:
    path = config_path(project_root) if callable(config_path) else project_root / config_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _provider(provider_id: str) -> ProviderDescriptor:
    return _DESCRIPTORS[provider_id]


@pytest.mark.parametrize("provider_id", _MCP_PROVIDERS)
def test_provider_mcp_writer_reader_remover_roundtrip(provider_id: str, tmp_path: Path) -> None:
    spec = _provider(provider_id).mcp_config
    path = _resolve_path(spec.config_path, tmp_path)
    entry = McpServerEntry(name="ag-cap-test", command="ag-cmd", args=("--flag", "val"))

    spec.writer(path, {"ag-cap-test": entry})
    assert path.exists(), f"{provider_id}: writer did not create {path}"

    read_back = spec.reader(path)
    assert "ag-cap-test" in read_back, f"{provider_id}: written MCP entry not read back"

    assert spec.remover(path, "ag-cap-test") is True, f"{provider_id}: remover did not report removal"
    assert "ag-cap-test" not in spec.reader(path), f"{provider_id}: entry still present after remove"


@pytest.mark.parametrize("provider_id", _MCP_PROVIDERS)
def test_provider_mcp_preserves_unmanaged_entries(provider_id: str, tmp_path: Path) -> None:
    spec = _provider(provider_id).mcp_config
    path = _resolve_path(spec.config_path, tmp_path)
    user_entry = McpServerEntry(name="user-server", command="user-cmd", args=())
    managed = McpServerEntry(name="ag-cap-test", command="ag-cmd", args=())

    spec.writer(path, {"user-server": user_entry})
    spec.writer(path, {"ag-cap-test": managed})
    spec.remover(path, "ag-cap-test")

    assert "user-server" in spec.reader(path), f"{provider_id}: unmanaged user entry lost"


@pytest.mark.parametrize("provider_id", _LS_PROVIDERS)
def test_provider_language_server_writer_reader_remover_roundtrip(provider_id: str, tmp_path: Path) -> None:
    spec = _provider(provider_id).language_servers_config
    path = _resolve_path(spec.config_path, tmp_path)
    entry = LanguageServerEntry(
        language="python",
        command=["pyright-langserver", "--stdio"],
        file_extensions=[".py"],
    )

    spec.writer(path, {"python": entry})
    assert path.exists(), f"{provider_id}: LS writer did not create {path}"

    read_back = spec.reader(path)
    assert "python" in read_back, f"{provider_id}: written LS entry not read back"

    assert spec.remover(path, "python") is True, f"{provider_id}: LS remover did not report removal"
    assert "python" not in spec.reader(path), f"{provider_id}: LS entry still present after remove"


def test_capability_provider_sets_are_non_empty() -> None:
    # Guard: if the registry changes shape, these parametrizations must still cover providers.
    assert _MCP_PROVIDERS, "expected providers declaring mcp_config"
    assert _LS_PROVIDERS, "expected providers declaring language_servers_config"
