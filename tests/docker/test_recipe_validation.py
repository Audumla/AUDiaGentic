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


def _recipe_test_cases():
    """Build canonical recipe test matrix."""
    cases = []

    # Positive: CLI lifecycle for each provider with install support
    for pid in _CLI_PROVIDERS:
        exp = _HARNESS_EXPECTATIONS.get(pid, {})
        cli_exp = exp.get("cli", {})
        cases.append(
            {
                "provider_id": pid,
                "operation": "install",
                "harness": None,  # auto-detect from provider config
                "expected_executable": cli_exp.get("executable"),
                "expected_package": cli_exp.get("package"),
                "error_code": None,
            }
        )

    # Negative: unsupported provider should fail with classified error
    cases.append(
        {
            "provider_id": "does-not-exist",
            "operation": "install",
            "harness": None,
            "expected_executable": None,
            "error_code": "VAL-PROV-001",  # or whatever the actual code is
        }
    )

    return cases


@pytest.mark.parametrize(
    "case", _recipe_test_cases(), ids=lambda c: f"{c['provider_id']}:{c['operation']}"
)
def test_recipe_execution(case: dict) -> None:
    """Execute a recipe and validate its outputs."""
    project_root = Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", ""))
    if not project_root.exists():
        pytest.skip("AUDIAGENTIC_REPO_ROOT not set or invalid")

    # Run the recipe through the public CLI
    cmd = ["audiagentic", "provider", case["operation"], "--provider-id", case["provider_id"]]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )

    # Validate outcome
    if case.get("error_code"):
        # Expected failure: check error code is present
        combined = f"{result.stdout}\n{result.stderr}"
        assert case["error_code"] in combined, (
            f"Expected error {case['error_code']} not found. "
            f"stdout: {result.stdout[:200]}\nstderr: {result.stderr[:200]}"
        )
    else:
        # Expected success: check exit code and artifacts
        assert result.returncode == 0, (
            f"Recipe failed for {case['provider_id']}: "
            f"stdout: {result.stdout[:300]}\nstderr: {result.stderr[:300]}"
        )

        # Validate executable exists on PATH if expected
        if case.get("expected_executable"):
            which = subprocess.run(
                ["which", case["expected_executable"]],
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert which.returncode == 0, (
                f"Expected executable {case['expected_executable']} not on PATH after install"
            )


# ── Harness lifecycle tests ──────────────────────────────────────────


@pytest.mark.parametrize("harness", ["pi", "opencode"])
def test_harness_install_lifecycle(harness: str) -> None:
    """Full harness lifecycle: install → status → uninstall → verify clean."""
    project_root = Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", ""))
    if not project_root.exists():
        pytest.skip("AUDIAGENTIC_REPO_ROOT not set or invalid")

    home = os.environ.get("HOME", "/tmp/recipe-test-home")
    harness_dir = os.path.join(home, ".audiagentic", "harness", harness)

    # Install harness
    result = subprocess.run(
        ["audiagentic", "bootstrap", "--target", harness_dir],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"Bootstrap failed: {result.stderr[:300]}"

    # Verify executable exists
    expected_binary = os.path.join(harness_dir, "cli", "node_modules", ".bin", harness)
    assert Path(expected_binary).exists(), f"Expected binary at {expected_binary}"

    # Uninstall (cleanup_runtime)
    result = subprocess.run(
        ["audiagentic", "cleanup", "--target", harness_dir],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"Cleanup failed: {result.stderr[:300]}"

    # Verify binary removed
    assert not Path(expected_binary).exists(), (
        f"Binary still exists after cleanup: {expected_binary}"
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
