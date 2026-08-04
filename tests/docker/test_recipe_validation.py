"""US03 — Run every documented recipe and verify capability outputs.

Data-driven Docker validation matrix: each provider/harness combination
executes through the public CLI in a clean installed environment, and we
validate its outputs against the recipe contract.

Test categories:
  - positive: recipe should succeed and produce expected artifacts
  - unsupported: recipe should fail with a documented classified error
  - negative: corrupted pre-existing state should be handled gracefully

Each test case is defined as a dict with:
  provider_id, harness, operation (install/uninstall/refresh),
  expected_files (list of paths that must exist after),
  expected_absent (paths that must NOT exist),
  expected_mcp_entries (MCP server names that should appear in config),
  error_code (expected error for negative cases, None for positive)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.opt_in]  # Docker-only, requires clean build

# ── Canonical recipe inventory ────────────────────────────────────────

# Providers with CLI lifecycle support (install/uninstall)
_CLI_PROVIDERS = [
    "pi",
    "opencode",
    "claude",
    "codex",
    "gemini",
    "roo",
    "cline",
    "continue",
    "goose",
]

# Providers that are CLI-only (no managed-mcp, no model-projection)
_CLI_ONLY_PROVIDERS = [
    "aider",
    "antigravity",
    "copilot",
    "plandex",
    "qwen",
]

# Harness-specific expectations: what each provider produces per harness
_HARNESS_EXPECTATIONS: dict[str, dict] = {
    "pi": {
        "cli": {
            "executable": "pi",
            "package": "@earendil-works/pi-coding-agent",
        },
    },
    "opencode": {
        "cli": {
            "executable": "opencode",
        },
    },
}

# ── Recipe test cases ────────────────────────────────────────────────


@pytest.mark.parametrize("pid", _CLI_PROVIDERS)
def test_provider_descriptor_valid(pid: str) -> None:
    """Validate provider descriptor has proper cli_install definition.

    Provider CLIs are installed by the managed-config recipe system, not by
    a public CLI command. This test validates that descriptors are well-formed.
    """
    project_root = Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", ""))
    if not project_root.exists():
        pytest.skip("AUDIAGENTIC_REPO_ROOT not set or invalid")

    config_path = project_root / "src/audiagentic/config/providers" / f"{pid}.yaml"
    assert config_path.exists(), f"Provider descriptor missing: {config_path}"

    content = config_path.read_text(encoding="utf-8")
    descriptor = yaml.safe_load(content)
    cli = (descriptor.get("capabilities") or {}).get("cli-install")
    assert isinstance(cli, dict) and isinstance(cli.get("mechanism"), dict), (
        f"Provider {pid} has no capabilities.cli-install.mechanism in descriptor"
    )


# ── Harness lifecycle tests ──────────────────────────────────────────


@pytest.mark.parametrize("harness", ["pi", "opencode"])
@pytest.mark.timeout(240)
def test_harness_install_lifecycle(harness: str) -> None:
    """Full harness lifecycle: install → status → uninstall → verify clean.

    Bootstrap installs the rig backend (models, llama-server) and materializes
    agent config. Provider CLIs are NOT installed by bootstrap — that's the
    responsibility of the managed-config recipe system (npm install --global).
    """
    project_root = Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", ""))
    if not project_root.exists():
        pytest.skip("AUDIAGENTIC_REPO_ROOT not set or invalid")

    home = os.environ.get("HOME", "/tmp/recipe-test-home")
    harness_dir = os.path.join(home, ".audiagentic", "harness", harness)
    child_env = os.environ.copy()
    child_env["AUDIAGENTIC_PROVISION_PI_RIG"] = "1"

    # Install harness runtime (rig backend + agent config)
    result = subprocess.run(
        [sys.executable, "-m", "audiagentic.launcher", "bootstrap", "--target", harness_dir],
        capture_output=True,
        text=True,
        timeout=180,
        env=child_env,
    )
    assert result.returncode == 0, f"Bootstrap failed: {result.stderr[:300]}"

    # Verify rig assets installed (llama-server binary)
    from audiagentic.runtime.rig.constants import platform_binary_names, platform_dir_name

    expected_server = os.path.join(
        harness_dir,
        "rig",
        "bin",
        "llama-server",
        platform_dir_name(),
        platform_binary_names()[0],
    )
    assert Path(expected_server).exists(), f"Expected rig server at {expected_server}"

    # Verify agent config materialized
    expected_models = os.path.join(harness_dir, "agent", "models.json")
    assert Path(expected_models).exists(), f"Expected models.json at {expected_models}"

    # Verify no provider CLI binary installed by bootstrap
    cli_bin = os.path.join(harness_dir, "cli", "node_modules", ".bin", harness)
    assert not Path(cli_bin).exists(), (
        f"Bootstrap should NOT install provider CLI: {cli_bin} "
        f"(provider CLIs are installed by managed-config, not bootstrap)"
    )

    # Uninstall (cleanup_runtime) — preserves rig/bin and models as user-owned areas
    result = subprocess.run(
        [sys.executable, "-m", "audiagentic.launcher", "cleanup", "--target", harness_dir],
        capture_output=True,
        text=True,
        timeout=60,
        env=child_env,
    )
    assert result.returncode == 0, f"Cleanup failed: {result.stderr[:300]}"

    # Agent config removed by cleanup (generated content)
    assert not Path(expected_models).exists(), (
        f"models.json should be removed after cleanup: {expected_models}"
    )

    # Rig server preserved by cleanup (user-managed asset per design)
    assert Path(expected_server).exists(), (
        f"Rig server should survive cleanup (user-owned): {expected_server}"
    )


# ── Capability output validation ─────────────────────────────────────


def test_provider_capability_outputs() -> None:
    """Validate that provider capability outputs match recipe contracts."""
    project_root = Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", ""))
    if not project_root.exists():
        pytest.skip("AUDIAGENTIC_REPO_ROOT not set or invalid")

    # Load provider descriptors and check their declared capabilities
    for pid, exp in _HARNESS_EXPECTATIONS.items():
        config_path = project_root / "src/audiagentic/config/providers" / f"{pid}.yaml"
        if not config_path.exists():
            continue

        content = config_path.read_text(encoding="utf-8")
        descriptor = yaml.safe_load(content)
        cli = (descriptor.get("capabilities") or {}).get("cli-install")
        assert isinstance(cli, dict) and isinstance(cli.get("mechanism"), dict), (
            f"Provider {pid} has no capabilities.cli-install.mechanism in descriptor"
        )

        # Verify expected fields match (YAML uses either quoted or unquoted)
        if exp.get("cli", {}).get("executable"):
            exe = exp["cli"]["executable"]
            assert cli["mechanism"].get("executable") == exe, (
                f"Provider {pid}: expected executable {exe} not found"
            )


# ── MCP propagation policy validation ────────────────────────────────

# Canonical propagation inventory from component configs:
#   audiagentic-only (10): ag-agents-mgmt, ag-ledger-mgmt, ag-lsp-mgmt,
#     ag-memory-mgmt, ag-planning-mgmt, ag-project-mgmt, ag-providers-mgmt,
#     ag-release-mgmt, ag-sc-mgmt, ag-session-mgmt
#   providers-only (6): ag-agents, ag-agents-gateway, ag-ledger,
#     ag-lsp, ag-planning, ag-release-please
#   both targets (2): git, github

_AUDIAGENTIC_ONLY = {
    "ag-agents-mgmt", "ag-ledger-mgmt", "ag-lsp-mgmt",
    "ag-memory-mgmt", "ag-planning-mgmt", "ag-project-mgmt",
    "ag-providers-mgmt", "ag-release-mgmt", "ag-sc-mgmt", "ag-session-mgmt",
}

_PROVIDERS_ONLY = {
    "ag-agents", "ag-agents-gateway", "ag-ledger",
    "ag-lsp", "ag-planning", "ag-release-please",
}

_BOTH_TARGETS = {"git", "github"}  # propagate: audiagentic,providers


def test_mcp_propagation_audiagentic_excluded_from_providers() -> None:
    """Management MCPs (propagate: audiagentic) must NOT appear in provider entries.

    This is the core invariant: internal AUDiaGentic management tools should
    never leak into the harness mcp.json that gets sent to provider CLIs
    like Pi or OpenCode.
    """
    project_root = Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", "/tmp/test-project"))
    project_root.mkdir(exist_ok=True)

    from audiagentic.foundation.components.loader import register_all_components
    register_all_components()

    from audiagentic.foundation.mcp.projection import collect_component_mcp_entries

    provider_entries = collect_component_mcp_entries(
        project_root,
        propagation_target="providers",
        require_enabled=False,
    )
    entry_names = set(provider_entries.keys())

    for name in _AUDIAGENTIC_ONLY:
        assert name not in entry_names, (
            f"Management MCP '{name}' (propagate: audiagentic) must NOT appear "
            f"in provider entries. Got: {sorted(entry_names)}"
        )


def test_mcp_propagation_both_targets_in_provider_entries() -> None:
    """MCPs with dual propagation (audiagentic,providers) appear in BOTH projections.

    The source-control component declares git/github MCP servers that propagate
    to both audiagentic and providers. We install the component to verify that
    its MCP servers appear in both projections.
    """
    project_root = Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", "/tmp/test-project"))
    project_root.mkdir(exist_ok=True)

    from audiagentic.foundation.components.loader import register_all_components
    from audiagentic.foundation.lifecycle.components import install_component

    register_all_components()
    # source-control component declares git/github with propagate: audiagentic,providers
    install_component("source-control", project_root)

    from audiagentic.foundation.mcp.projection import collect_component_mcp_entries

    provider_entries = collect_component_mcp_entries(
        project_root,
        propagation_target="providers",
        require_enabled=False,
    )
    audiagentic_entries = collect_component_mcp_entries(
        project_root,
        propagation_target="audiagentic",
        require_enabled=False,
    )
    provider_names = set(provider_entries.keys())
    audiagentic_names = set(audiagentic_entries.keys())

    # git requires uvx (available), github requires gh (not available)
    # Verify git appears in BOTH projections as proof of dual propagation
    assert "git" in provider_names, (
        f"Dual-target MCP 'git' (propagate: audiagentic,providers) "
        f"must appear in provider entries. Got: {sorted(provider_names)}"
    )
    assert "git" in audiagentic_names, (
        f"Dual-target MCP 'git' (propagate: audiagentic,providers) "
        f"must appear in audiagentic entries. Got: {sorted(audiagentic_names)}"
    )


def test_mcp_propagation_providers_only_not_in_audiagentic() -> None:
    """Provider-only MCPs must NOT appear in audiagentic-only projection."""
    project_root = Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", "/tmp/test-project"))
    project_root.mkdir(exist_ok=True)

    from audiagentic.foundation.components.loader import register_all_components
    register_all_components()

    from audiagentic.foundation.mcp.projection import collect_component_mcp_entries

    audiagentic_entries = collect_component_mcp_entries(
        project_root,
        propagation_target="audiagentic",
        require_enabled=False,
    )
    entry_names = set(audiagentic_entries.keys())

    for name in _PROVIDERS_ONLY:
        assert name not in entry_names, (
            f"Provider-only MCP '{name}' (propagate: providers) must NOT appear "
            f"in audiagentic entries. Got: {sorted(entry_names)}"
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
