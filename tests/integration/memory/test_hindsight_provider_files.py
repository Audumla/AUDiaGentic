"""Per-provider Hindsight file-provisioning validation.

For every provider whose Hindsight strategy writes files into the project (MCP
config entries and/or rule blocks — not the subprocess installers), this checks
the full round-trip when the memory/Hindsight implementation is configured:

    configure backend -> reconcile -> provider files reference Hindsight
                      -> reconcile without backend -> files are clean again

Runs inside the standard Docker suite (``pytest -m "not mutates_host"``). Strategy
resolution is platform-aware, so each provider is validated as it would behave on
the host running the test. Subprocess-installer kinds (hooks/plugin/wrapper) are
excluded — those write to global/external paths and need the real installer.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import audiagentic.components.providers  # noqa: F401  (register provider descriptors)
from audiagentic.components.memory.hindsight import provision as prov
from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.matrix import HINDSIGHT_RECIPE_MATRIX
from audiagentic.components.memory.hindsight.recipes import resolve_hindsight_strategy
from audiagentic.components.providers.services.recipes import ProviderRecipeKind

# Kinds that shell out to an external installer (global/network side effects).
_SUBPROCESS_KINDS = {
    ProviderRecipeKind.HOOKS,
    ProviderRecipeKind.PLUGIN_CONFIG,
    ProviderRecipeKind.WRAPPER_CLI,
}
# Kinds that always write a project config file when a backend is configured.
_MUST_WRITE_KINDS = {ProviderRecipeKind.MCP_CONFIG, ProviderRecipeKind.HYBRID}


def _file_writing_providers() -> list[str]:
    # Providers whose recipe writes project files without shelling out to an
    # installer (validated in the normal suite). Installer-style providers run
    # real installs and are covered by the Docker per-provider test instead.
    providers: list[str] = []
    for row in HINDSIGHT_RECIPE_MATRIX:
        resolved = resolve_hindsight_strategy(row.provider_id)
        if resolved is None or resolved.recipe_kind in _SUBPROCESS_KINDS:
            continue
        providers.append(row.provider_id)
    return providers


def _hindsight_files(root: Path) -> list[Path]:
    return [
        p for p in root.rglob("*")
        if p.is_file() and "hindsight" in p.read_text(encoding="utf-8", errors="ignore").lower()
    ]


@pytest.mark.parametrize("provider_id", _file_writing_providers())
def test_provider_files_provisioned_and_reverted(provider_id, tmp_path, monkeypatch):
    backend = HindsightBackendConfig(base_url="http://hindsight.test:8000/", api_key="k")
    monkeypatch.setattr(prov, "build_hindsight_backend", lambda root: backend)

    # Configure + provision.
    applied = prov.reconcile_hindsight(tmp_path, [provider_id])
    assert applied["action"] == "applied"

    # Assert on the file outcome, not the success flag: a HYBRID provider may
    # carry an optional subprocess installer that fails here while its config /
    # rule artifacts are still written correctly (that is what we validate).
    files = _hindsight_files(tmp_path)
    resolved = resolve_hindsight_strategy(provider_id, tmp_path)
    if resolved.recipe_kind in _MUST_WRITE_KINDS:
        assert files, f"{provider_id}: expected a project file referencing hindsight"

    # Tear down (no backend) — every file written above must be cleaned.
    monkeypatch.setattr(prov, "build_hindsight_backend", lambda root: None)
    prov.reconcile_hindsight(tmp_path, [provider_id])
    assert not _hindsight_files(tmp_path), f"{provider_id}: hindsight refs left after teardown"
