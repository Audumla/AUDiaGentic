"""Opt-in LIVE per-provider Hindsight validation on the real host.

Unlike the Docker-gated e2e suite, this runs against the provider CLIs actually
installed on the developer's machine, so it exercises host-platform execution
paths (npm/.cmd shim resolution, console encoding) that a Linux image cannot
reproduce. It is:

* **opt-in** — skipped unless ``AUDIAGENTIC_LIVE_PROVIDER_TESTS=1`` is set, so it
  never runs in the normal suite (it invokes real installers).
* **CLI-gated** — each provider is skipped unless its CLI is on PATH.
* **isolated + non-persistent** — HOME/USERPROFILE are redirected to a tmp dir so
  installers write there, never the real home; every case also tears down in a
  ``finally`` block and asserts the integration is gone afterward.

The assertions check *observed* state (``claude plugin list``, the provider
config file, the installer's ``~/.hindsight`` artifacts), not the recipe's
self-report — which is how a recipe that falsely reports success (or an
incomplete teardown) gets caught.

Run it explicitly:

    AUDIAGENTIC_LIVE_PROVIDER_TESTS=1 pytest tests/integration/providers/test_provider_hindsight_live.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

import audiagentic.components.providers  # noqa: F401  (register provider descriptors)
from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.lifecycle import (
    apply_hindsight,
    teardown_hindsight,
)
from audiagentic.components.memory.hindsight.matrix import (
    HINDSIGHT_RECIPE_MATRIX,
    get_rows_for_provider,
)
from audiagentic.components.providers.descriptors.registry import get_descriptor

pytestmark = [
    pytest.mark.opt_in,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("AUDIAGENTIC_LIVE_PROVIDER_TESTS") != "1",
        reason="opt-in live host validation; set AUDIAGENTIC_LIVE_PROVIDER_TESTS=1 to run",
    ),
]

_BACKEND = HindsightBackendConfig(base_url="http://hindsight-live.test:8888", api_key="live-token")
_RULE_MARKER = "audiagentic:hindsight-memory"

# Provider-specific installer artifacts (hooks kinds), scoped to the isolated
# home. Checking the provider's own file avoids the shared ~/.hindsight dir that
# multiple providers populate.
_INSTALLER_ARTIFACT = {
    "codex": lambda home: home / ".codex" / "hooks.json",
    "cline": lambda home: home / ".hindsight" / "cline.json",
}

# Providers whose integration is expected to actually install/verify when their
# CLI is present. The rest (guidance-only / fragile external installers) are
# expected to no-op or fail cleanly — but must STILL leave nothing behind.
_EXPECT_INSTALL = {
    "claude", "gemini", "openhands", "opencode", "copilot", "roo",
    "cline", "codex", "qwen", "continue",
}


def _cli_executable(provider_id: str) -> str:
    descriptor = get_descriptor(provider_id)
    probe = getattr(descriptor, "cli_probe", None) if descriptor else None
    if isinstance(probe, str):
        return probe
    if isinstance(probe, dict) and probe.get("executable"):
        return probe["executable"]
    return provider_id


def _observed_installed(provider_id: str, project: Path, home: Path) -> bool:
    """Independently observe whether Hindsight is installed for a provider.

    Uses real, recipe-agnostic signals scoped to the isolated home/project:
    the provider CLI's plugin listing, the provider MCP config file, a managed
    rule block in project files, or the installer's ~/.hindsight artifacts.
    """
    if provider_id == "claude":
        exe = shutil.which("claude")
        if exe is None:
            return False
        env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
        out = subprocess.run(
            [exe, "plugin", "list"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
        ).stdout or ""
        return "hindsight-memory" in out

    descriptor = get_descriptor(provider_id)
    spec = descriptor.mcp_config if descriptor else None
    if spec is not None:
        config_path = spec.config_path(project) if callable(spec.config_path) else project / spec.config_path
        if config_path.exists() and "hindsight" in spec.reader(config_path):
            return True

    # Hooks installers: check the provider-specific artifact, not the shared
    # ~/.hindsight directory (which other providers also populate).
    installer_artifact = _INSTALLER_ARTIFACT.get(provider_id)
    if installer_artifact is not None and installer_artifact(home).exists():
        return True

    # Rule-block providers write a managed marker into a project rules file.
    for path in project.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".md", ".mdx", ".json", ".toml", ".yaml"}:
            try:
                if _RULE_MARKER in path.read_text(encoding="utf-8", errors="ignore"):
                    return True
            except OSError:
                continue
    return False


_MATRIX_PROVIDERS = sorted(row.provider_id for row in HINDSIGHT_RECIPE_MATRIX)


@pytest.mark.parametrize("provider_id", _MATRIX_PROVIDERS)
@pytest.mark.timeout(600)
def test_provider_hindsight_install_teardown_cycle(provider_id, tmp_path, monkeypatch):
    """apply installs (observably), teardown fully restores — checked against real state.

    HOME/USERPROFILE are redirected into tmp so real installers write there and the
    developer's actual home is never touched.
    """
    if shutil.which(_cli_executable(provider_id)) is None:
        pytest.skip(f"{provider_id} CLI not installed on this host")

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(project)

    kind = get_rows_for_provider(provider_id)[0].recipe_kind.value
    try:
        result = apply_hindsight(project, backend=_BACKEND, provider_ids=[provider_id])[provider_id]

        if provider_id in _EXPECT_INSTALL:
            assert result.success, f"{provider_id}: apply failed: {result.error}"
            assert _observed_installed(provider_id, project, home), (
                f"{provider_id}: recipe reported success but no integration is observable "
                f"(kind={kind})"
            )
        else:
            # Guidance-only / fragile installers: must not falsely claim success.
            assert not _observed_installed(provider_id, project, home), (
                f"{provider_id}: unexpected integration left by a no-op/failed apply"
            )
    finally:
        teardown_hindsight(project, backend=_BACKEND, provider_ids=[provider_id])

    # The key reversibility guarantee: nothing is left behind.
    assert not _observed_installed(provider_id, project, home), (
        f"{provider_id}: teardown did not remove the integration (observed still present)"
    )


def test_live_specs_cover_all_matrix_providers():
    """Guard: every matrix provider is parametrized, so none silently drops out."""
    assert set(_MATRIX_PROVIDERS) == {row.provider_id for row in HINDSIGHT_RECIPE_MATRIX}
