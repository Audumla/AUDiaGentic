"""Hindsight provisioning e2e — runs inside the provider-lifecycle Docker image.

Each provider's Hindsight recipe is exercised from a clean state inside the same
Docker image that already installs provider CLIs (Dockerfile.provider-lifecycle-e2e).
This avoids a separate image: the lifecycle image has pip, curl, and every
provider CLI already available on PATH.

Per-provider specs are explicit — there is no single uniform behaviour:
  mcp       MCP/config entry written into the provider's harness config file.
  installer Native hooks installer runs (e.g. hindsight-cline) and writes
            connection config referencing the test server.
  rules     A managed rule block is written (no server URL, no CLI).
  skip      Not testable here; concrete reason given.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import audiagentic.components.providers  # noqa: F401  register descriptors
from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.recipes import apply_hindsight

pytestmark = [
    pytest.mark.slow,
    pytest.mark.mutates_host,
    pytest.mark.skipif(
        os.environ.get("AUDIAGENTIC_DOCKER_TESTS") != "1",
        reason="Hindsight e2e requires Docker harness",
    ),
    pytest.mark.skipif(
        os.environ.get("AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS") != "1",
        reason="Hindsight e2e requires the provider-lifecycle Docker image",
    ),
]

_NEEDLE = "hindsight-e2e.test:8888"
_SERVER = f"http://{_NEEDLE}/"
_RULE_MARKER = "audiagentic:hindsight-memory"

# Explicit per-provider expectation. Skip reasons are concrete on purpose.
_SPECS: dict[str, tuple[str, str]] = {
    # MCP / config-write recipes — no CLI install needed, just file writes.
    "gemini":       ("mcp", ""),
    "copilot":      ("mcp", ""),       # hybrid → .vscode/mcp.json
    "openhands":    ("mcp", ""),       # hybrid → config.toml + AGENTS.md rule
    "roo":          ("mcp", ""),       # hybrid → .roo/mcp.json + rules
    "continue":     ("mcp", ""),       # hybrid → continue.json MCP entry
    "opencode":     ("mcp", ""),       # plugin_config + manage_config_writes
    # Hook installer — pip package publishes a CLI that writes ~/.hindsight/cline.json.
    "cline":        ("installer", ""),
    # Rule-only recipes.
    "qwen":         ("rules", ""),
    # Skipped with concrete reasons.
    "codex":        ("skip", "curl|bash installer does not accept --api-url; server URL is runtime config, not install-time"),
    "claude":       ("skip", "requires an authenticated `claude` CLI session; marketplace auth not available in CI"),
    "aider":        ("skip", "hindsight-aider not on PyPI (404)"),
    "goose":        ("skip", "no Hindsight integration"),
    "local-openai": ("skip", "no Hindsight integration"),
    "pi":           ("skip", "no Hindsight integration"),
    "plandex":      ("skip", "no Hindsight integration"),
}


def _files(*roots: Path) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        out.extend(p for p in root.rglob("*") if p.is_file())
    return out


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


@pytest.mark.parametrize("provider_id", sorted(_SPECS))
@pytest.mark.timeout(300)
def test_hindsight_provisioning(provider_id: str, tmp_path: Path, monkeypatch) -> None:
    kind, reason = _SPECS[provider_id]
    if kind == "skip":
        pytest.skip(reason)

    # Isolate HOME so installer CLIs write into a scratch directory, not the
    # real home. Run from a clean project directory so config writes land there.
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(project)

    backend = HindsightBackendConfig(base_url=_SERVER, api_key="e2e-token")
    result = apply_hindsight(project, backend=backend, provider_ids=[provider_id])[provider_id]
    assert result.success, f"{provider_id} provisioning failed: {result.error}"

    files = _files(home, project)
    if kind in ("mcp", "installer"):
        referencing = [p for p in files if _NEEDLE in _read(p)]
        assert referencing, f"{provider_id}: no provisioned file references {_NEEDLE!r}"
    elif kind == "rules":
        assert any(_RULE_MARKER in _read(p) for p in files), \
            f"{provider_id}: expected managed Hindsight rule block"
