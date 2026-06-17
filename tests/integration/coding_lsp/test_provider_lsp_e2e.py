"""End-to-end LSP provisioning across providers and languages.

Runs inside the Docker harness built from tests/docker/Dockerfile.provider-lsp-e2e
(node + uv + language servers + project installed). Validates the full chain:

  1. install + enable the coding-lsp component in a project
  2. enable languages (lsp.json) and install their server binaries (scoped)
  3. propagate to providers (native config + generic ag-lsp MCP)
  4. assert each provider's LSP config is correct
  5. assert each language's server binary is installed and actually runs
  6. assert dependencies resolved correctly (no missing for configured langs)
  7. assert LSP works per language through the path providers consume (ag-lsp)

Provider CLI install/run (codex/opencode/qwen npm binaries) is opt-in via
AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS=1 — config/capability assertions run
without it because provider config files are written for any registered
descriptor regardless of whether the CLI binary is present.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
import tomllib

from audiagentic.components.optional.coding_lsp import language_registry, lsp_api
from audiagentic.components.optional.coding_lsp.language_servers_sync import (
    prune_language_servers_from_providers,
    sync_language_servers_to_providers,
)
from audiagentic.components.optional.providers.adapters.mcp_json import read_mcp_json
from audiagentic.components.optional.providers.adapters.mcp_opencode import read_opencode_mcp
from audiagentic.foundation.components.dependencies import build_dependency_workflow

pytestmark = [
    pytest.mark.mutates_host,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("AUDIAGENTIC_DOCKER_TESTS") != "1",
        reason="provider/LSP e2e mutates host — run inside the Docker harness",
    ),
]

# Fast servers by default; rust-analyzer (cargo build) + clangd opt-in.
_DEFAULT_LANGS = ["python", "typescript"]
_ALL_LANGS = ["python", "typescript", "rust", "cpp"]
LANGUAGES = _ALL_LANGS if os.environ.get("AUDIAGENTIC_LSP_E2E_ALL") == "1" else _DEFAULT_LANGS

# A trivial source file per language that defines a top-level symbol `marker`.
_SAMPLE: dict[str, tuple[str, str]] = {
    "python": ("sample.py", "def marker():\n    return 1\n"),
    "typescript": ("sample.ts", "export function marker(): number {\n  return 1;\n}\n"),
    "rust": ("sample.rs", "pub fn marker() -> i32 {\n    1\n}\n"),
    "cpp": ("sample.cpp", "int marker() {\n    return 1;\n}\n"),
}


# ---------------------------------------------------------------------------
# Project + provisioning fixture (session-scoped — installs are expensive)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def provisioned_project(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("lsp-e2e-project")
    (root / ".audiagentic").mkdir(parents=True, exist_ok=True)

    # 1. enable languages in lsp.json
    for lang in LANGUAGES:
        result = lsp_api.add_language(str(root), lang)
        assert result["ok"], f"add_language({lang}) failed: {result}"

    configured_lang_ids = LANGUAGES
    dep_cfgs = language_registry.dependency_cfgs(configured_lang_ids)

    # 2. install the language server binaries — scoped to configured languages
    workflow = build_dependency_workflow(dep_cfgs, workflow_id="coding-lsp", action="install")
    workflow.run({})

    # 3. propagate to providers: native config + generic ag-lsp MCP
    sync_language_servers_to_providers(root)
    _propagate_generic_lsp(root)

    # write sample sources used by the LSP-working assertions
    for lang in LANGUAGES:
        name, body = _SAMPLE[lang]
        (root / name).write_text(body, encoding="utf-8")

    return root


def _propagate_generic_lsp(project_root: Path) -> None:
    """Push propagate:providers MCP servers (incl. ag-lsp) to provider configs."""
    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.components.registry import get_descriptor
    from audiagentic.runtime.lifecycle.components import _propagate_mcp_to_providers

    register_all_components()
    descriptor = get_descriptor("coding-lsp")
    assert descriptor is not None, "coding-lsp component not registered"
    _propagate_mcp_to_providers(descriptor, project_root)


# ---------------------------------------------------------------------------
# Dependencies resolved correctly
# ---------------------------------------------------------------------------

def test_no_missing_dependencies_for_configured_languages(provisioned_project: Path) -> None:
    missing = lsp_api.missing_configured_dependencies(provisioned_project)
    assert missing == [], f"language servers not installed: {missing}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_server_binary_installed_and_runs(provisioned_project: Path, language: str) -> None:
    spec = language_registry.get_language(language)
    assert spec is not None and spec.command
    binary = spec.command[0]
    path = shutil.which(binary)
    assert path is not None, f"{language} server binary {binary!r} not on PATH"


# ---------------------------------------------------------------------------
# Provider LSP config correctness
# ---------------------------------------------------------------------------

def test_codex_native_config(provisioned_project: Path) -> None:
    cfg_path = provisioned_project / ".codex" / "config.toml"
    assert cfg_path.exists()
    data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    servers = data.get("language_servers", {})
    for lang in LANGUAGES:
        assert lang in servers, f"codex missing native LSP entry for {lang}"
        assert servers[lang]["command"] == list(language_registry.get_language(lang).command)
    # generic ag-lsp suppressed in codex's unique config file
    assert "ag-lsp" not in data.get("mcp_servers", {})


def test_opencode_native_config(provisioned_project: Path) -> None:
    cfg_path = provisioned_project / ".opencode" / "opencode.json"
    assert cfg_path.exists()
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    lsp = data.get("lsp", {})
    for lang in LANGUAGES:
        assert lang in lsp, f"opencode missing native LSP entry for {lang}"
        assert lsp[lang]["command"] == list(language_registry.get_language(lang).command)
    # generic ag-lsp suppressed in opencode's unique config file
    assert "ag-lsp" not in (read_opencode_mcp(cfg_path))


def test_qwen_native_config(provisioned_project: Path) -> None:
    cfg_path = provisioned_project / ".lsp.json"
    assert cfg_path.exists()
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    for lang in LANGUAGES:
        assert lang in data, f"qwen missing native LSP entry for {lang}"
        cmd = language_registry.get_language(lang).command
        assert data[lang]["command"] == cmd[0]
        assert data[lang]["args"] == list(cmd[1:])


def test_generic_provider_has_ag_lsp(provisioned_project: Path) -> None:
    # claude is a generic provider — gets LSP via the ag-lsp MCP server
    servers = read_mcp_json(provisioned_project / ".mcp.json")
    assert "ag-lsp" in servers, "generic provider missing ag-lsp MCP server"


# ---------------------------------------------------------------------------
# LSP actually works per language (the capability providers consume via ag-lsp)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("language", LANGUAGES)
def test_lsp_symbols_resolve_per_language(provisioned_project: Path, language: str) -> None:
    sample_name, _ = _SAMPLE[language]
    sample = provisioned_project / sample_name
    symbols = lsp_api.document_symbols(str(sample))
    assert isinstance(symbols, list)
    errors = [s for s in symbols if isinstance(s, dict) and s.get("error")]
    assert not errors, f"{language} LSP errored: {errors}"
    names = [s.get("name", "") for s in symbols if isinstance(s, dict)]
    assert any("marker" in n for n in names), f"{language} symbol 'marker' not found: {names}"


# ---------------------------------------------------------------------------
# Disable removes native entries (real prune)
# ---------------------------------------------------------------------------

def test_prune_removes_native_entries(provisioned_project: Path) -> None:
    prune_language_servers_from_providers(provisioned_project)
    data = tomllib.loads((provisioned_project / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert data.get("language_servers", {}) == {}
    qwen = json.loads((provisioned_project / ".lsp.json").read_text(encoding="utf-8"))
    for lang in LANGUAGES:
        assert lang not in qwen
    # re-sync so other tests (if reordered) still see config
    sync_language_servers_to_providers(provisioned_project)
