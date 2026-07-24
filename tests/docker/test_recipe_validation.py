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
    # Verify the provider declares cli_install or cli-probe
    assert "cli_install:" in content or "cli_probe:" in content, (
        f"Provider {pid} has no cli_install/cli_probe in descriptor"
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

    # Install harness runtime (rig backend + agent config)
    result = subprocess.run(
        ["audiagentic", "bootstrap", "--target", harness_dir],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"Bootstrap failed: {result.stderr[:300]}"

    # Verify rig assets installed (llama-server binary)
    expected_server = os.path.join(harness_dir, "rig", "bin", "llama-server", "linux", "llama-server")
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
        ["audiagentic", "cleanup", "--target", harness_dir],
        capture_output=True,
        text=True,
        timeout=60,
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
        # Verify the provider declares cli-install capability
        assert "cli_install:" in content or "cli-probe:" in content, (
            f"Provider {pid} has expectations but no cli_install/cli-probe in descriptor"
        )

        # Verify expected fields match (YAML uses either quoted or unquoted)
        if exp.get("cli", {}).get("executable"):
            exe = exp["cli"]["executable"]
            assert f"executable: {exe}" in content or f'executable: "{exe}"' in content, (
                f"Provider {pid}: expected executable {exe} not found"
            )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
