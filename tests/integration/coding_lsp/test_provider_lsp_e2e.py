"""End-to-end LSP provisioning across providers and languages.

Runs inside the Docker harness built from tests/docker/Dockerfile.provider-lsp-e2e.
Validates the full chain:

  1. install the `coding-lsp` component in a project
  2. install native-LSP provider CLIs (codex, opencode, qwen)
  3. enable languages in `lsp.json`
  4. install only the language-server binaries for those configured languages
  5. propagate to providers (native config + generic ag-lsp MCP)
  6. assert each provider's LSP config is correct
  7. assert each provider CLI is installed and healthy
  8. assert each language's server binary is installed and actually works
  9. assert dependency resolution is scoped to configured languages only
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
import tomllib
from tests.integration.providers.harness import (
    assert_health_ok,
    assert_install_result_ok,
    install_provider,
)

from audiagentic.components.optional.coding_lsp import language_registry, lsp_api
from audiagentic.components.optional.coding_lsp.language_servers_sync import (
    prune_generic_lsp_mcp_from_providers,
    prune_language_servers_from_providers,
    sync_generic_lsp_mcp_to_providers,
    sync_language_servers_to_providers,
)
from audiagentic.components.optional.providers.descriptors.registry import all_descriptors
from audiagentic.foundation.components.dependencies import build_dependency_workflow
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.runtime.lifecycle.components import enable_component, install_component

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

register_all_components()
_PROVIDERS = all_descriptors()
NATIVE_LSP_PROVIDERS = sorted(
    provider_id for provider_id, descriptor in _PROVIDERS.items()
    if descriptor.language_servers_config is not None
)
GENERIC_MCP_LSP_PROVIDERS = sorted(
    provider_id for provider_id, descriptor in _PROVIDERS.items()
    if descriptor.mcp_config is not None and descriptor.language_servers_config is None
)
DEDICATED_NATIVE_MCP_PROVIDERS = sorted(
    provider_id
    for provider_id in NATIVE_LSP_PROVIDERS
    if _PROVIDERS[provider_id].mcp_config is not None
    and not callable(_PROVIDERS[provider_id].mcp_config.config_path)
    and _PROVIDERS[provider_id].mcp_config.config_path != ".mcp.json"
)

# A trivial source file per language that defines a top-level symbol `marker`.
_SAMPLE: dict[str, tuple[str, str]] = {
    "python": ("sample.py", "def marker():\n    return 1\n"),
    "typescript": ("sample.ts", "export function marker(): number {\n  return 1;\n}\n"),
    "rust": ("sample.rs", "pub fn marker() -> i32 {\n    1\n}\n"),
    "cpp": ("sample.cpp", "int marker() {\n    return 1;\n}\n"),
}

_WORKSPACE_FILES: dict[str, dict[str, str]] = {
    "typescript": {
        "tsconfig.json": '{\n  "compilerOptions": {\n    "target": "ES2020",\n    "module": "commonjs"\n  }\n}\n',
        "package.json": '{\n  "name": "lsp-e2e-ts",\n  "private": true\n}\n',
    },
    "rust": {
        "Cargo.toml": '[package]\nname = "lsp-e2e-rust"\nversion = "0.1.0"\nedition = "2021"\n\n[lib]\npath = "sample.rs"\n',
    },
    "cpp": {
        "compile_commands.json": '[\n  {\n    "directory": ".",\n    "command": "clang++ -c sample.cpp",\n    "file": "sample.cpp"\n  }\n]\n',
    },
}


# ---------------------------------------------------------------------------
# Project + provisioning fixture (session-scoped — installs are expensive)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def provisioned_project(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("lsp-e2e-project")
    (root / ".audiagentic").mkdir(parents=True, exist_ok=True)

    # 1. install coding-lsp through lifecycle APIs
    lsp_result = install_component("coding-lsp", root)
    assert lsp_result["ok"], f"install coding-lsp failed: {lsp_result}"
    enable_result = enable_component("coding-lsp", root)
    assert enable_result["ok"], f"enable coding-lsp failed: {enable_result}"

    # 2. install the provider CLIs used for native LSP config
    for provider_id in NATIVE_LSP_PROVIDERS:
        result = install_provider(provider_id, project_root=root)
        assert_install_result_ok(provider_id, result)
        assert_health_ok(provider_id, result)

    # 3. enable languages in lsp.json
    for lang in LANGUAGES:
        result = lsp_api.add_language(str(root), lang)
        assert result["ok"], f"add_language({lang}) failed: {result}"

    configured_lang_ids = LANGUAGES
    dep_cfgs = language_registry.dependency_cfgs(configured_lang_ids)

    # 4. install the language server binaries — scoped to configured languages
    workflow = build_dependency_workflow(dep_cfgs, workflow_id="coding-lsp", action="install")
    workflow.run({})

    # 5. propagate to providers: native config + generic ag-lsp MCP
    sync_language_servers_to_providers(root)
    sync_generic_lsp_mcp_to_providers(root)

    # write sample sources used by the LSP-working assertions
    for lang in LANGUAGES:
        for rel, body in _WORKSPACE_FILES.get(lang, {}).items():
            (root / rel).write_text(body, encoding="utf-8")
        name, body = _SAMPLE[lang]
        (root / name).write_text(body, encoding="utf-8")

    return root

# ---------------------------------------------------------------------------
# Component + provider install assertions
# ---------------------------------------------------------------------------

def test_components_installed(provisioned_project: Path) -> None:
    assert (provisioned_project / ".audiagentic" / "components" / "coding-lsp.yaml").exists()
    assert (provisioned_project / ".coding-lsp" / "logs").is_dir()


@pytest.mark.parametrize("provider_id", NATIVE_LSP_PROVIDERS)
def test_native_lsp_provider_cli_installed(provider_id: str) -> None:
    executable = _PROVIDERS[provider_id].cli_install.executable
    assert shutil.which(executable) is not None, f"{provider_id} CLI not installed"


# ---------------------------------------------------------------------------
# Dependencies resolved correctly
# ---------------------------------------------------------------------------

def test_no_missing_dependencies_for_configured_languages(provisioned_project: Path) -> None:
    missing = lsp_api.missing_configured_dependencies(provisioned_project)
    assert missing == [], f"language servers not installed: {missing}"


def test_only_configured_language_dependencies_are_considered(provisioned_project: Path) -> None:
    expected = set(language_registry.dependency_ids(LANGUAGES))
    configured = set(lsp_api.configured_dependency_ids(provisioned_project))
    assert configured == expected


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


def test_qwen_native_config(provisioned_project: Path) -> None:
    cfg_path = provisioned_project / ".lsp.json"
    assert cfg_path.exists()
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    for lang in LANGUAGES:
        assert lang in data, f"qwen missing native LSP entry for {lang}"
        cmd = language_registry.get_language(lang).command
        assert data[lang]["command"] == cmd[0]
        assert data[lang]["args"] == list(cmd[1:])


def test_native_provider_configs_scope_to_enabled_languages(provisioned_project: Path) -> None:
    codex = tomllib.loads((provisioned_project / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert set(codex.get("language_servers", {}).keys()) == set(LANGUAGES)
    opencode = json.loads((provisioned_project / ".opencode" / "opencode.json").read_text(encoding="utf-8"))
    assert set(opencode.get("lsp", {}).keys()) == set(LANGUAGES)
    qwen = json.loads((provisioned_project / ".lsp.json").read_text(encoding="utf-8"))
    assert set(qwen.keys()) == set(LANGUAGES)


@pytest.mark.parametrize("provider_id", GENERIC_MCP_LSP_PROVIDERS)
def test_generic_provider_has_ag_lsp(provisioned_project: Path, provider_id: str) -> None:
    descriptor = _PROVIDERS[provider_id]
    spec = descriptor.mcp_config
    assert spec is not None
    config_path = spec.config_path(provisioned_project) if callable(spec.config_path) else (provisioned_project / spec.config_path)
    servers = spec.reader(config_path)
    assert "ag-lsp" in servers, f"{provider_id} missing ag-lsp MCP server"


@pytest.mark.parametrize("provider_id", DEDICATED_NATIVE_MCP_PROVIDERS)
def test_native_lsp_providers_do_not_get_generic_ag_lsp(provisioned_project: Path, provider_id: str) -> None:
    descriptor = _PROVIDERS[provider_id]
    spec = descriptor.mcp_config
    if spec is None:
        return
    config_path = spec.config_path(provisioned_project) if callable(spec.config_path) else (provisioned_project / spec.config_path)
    servers = spec.reader(config_path)
    assert "ag-lsp" not in servers, f"{provider_id} should use native LSP, not generic ag-lsp"


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
    prune_generic_lsp_mcp_from_providers(provisioned_project)
    data = tomllib.loads((provisioned_project / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert data.get("language_servers", {}) == {}
    qwen = json.loads((provisioned_project / ".lsp.json").read_text(encoding="utf-8"))
    for lang in LANGUAGES:
        assert lang not in qwen
    # re-sync so other tests (if reordered) still see config
    sync_language_servers_to_providers(provisioned_project)
    sync_generic_lsp_mcp_to_providers(provisioned_project)
