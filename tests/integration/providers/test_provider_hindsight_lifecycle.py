"""Per-provider Hindsight provisioning e2e inside provider lifecycle image.

Runs real Hindsight recipes in the same clean Docker image used for provider
lifecycle coverage. This avoids maintaining a second near-duplicate image while
still keeping each test isolated under tmp_path/HOME.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import audiagentic.components.providers  # noqa: F401  (register descriptors)
from audiagentic.components.memory.hindsight.matrix import HINDSIGHT_RECIPE_MATRIX
from audiagentic.components.memory.hindsight.mcp_recipe import build_hindsight_entry
from audiagentic.components.memory.hindsight.recipes import apply_hindsight
from audiagentic.components.memory.hindsight_export import HindsightBackendConfig
from audiagentic.components.providers.descriptors.registry import get_descriptor
from audiagentic.components.providers.services.lifecycle import (
    install_provider_cli,
    uninstall_provider_cli,
)
from audiagentic.foundation.mcp import McpServerEntry

pytestmark = [
    pytest.mark.slow,
    pytest.mark.mutates_host,
    pytest.mark.skipif(
        os.environ.get("AUDIAGENTIC_DOCKER_TESTS") != "1",
        reason="Hindsight provider install e2e requires the Docker harness",
    ),
]

_NEEDLE = "hindsight-e2e.test:8888"
_SERVER = f"http://{_NEEDLE}/"
_RULE_MARKER = "audiagentic:hindsight-memory"
_PREINSTALL_PROVIDER_CLI = {"claude"}

_SPECS: dict[str, tuple[str, str]] = {
    "gemini": ("success-mcp", ""),
    "copilot": ("success-hybrid", ""),
    "openhands": ("success-mcp", ""),
    "roo": ("success-hybrid", ""),
    "cline": ("success-installer", ""),
    "codex": ("success-installer", ""),
    "opencode": ("success-mcp", ""),
    "qwen": ("success-rules", ""),
    "continue": ("success-mcp", ""),
    "claude": ("success-plugin", ""),
    "aider": ("expected-failure", "hindsight-aider"),
    "goose": ("expected-failure", "no Hindsight integration"),
    "local-openai": ("expected-failure", "no Hindsight integration"),
    "plandex": ("expected-failure", "no Hindsight integration"),
    "pi": ("expected-failure", "no Hindsight integration"),
}

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _expected_mcp_entry(backend: HindsightBackendConfig) -> McpServerEntry:
    entry = build_hindsight_entry(backend)
    if "url" in entry:
        return McpServerEntry(
            name=backend.server_name,
            url=entry["url"],
            headers=dict(entry.get("headers", {})),
            transport=entry.get("type"),
        )
    return McpServerEntry(
        name=backend.server_name,
        command=entry.get("command", ""),
        args=tuple(entry.get("args", [])),
        env=dict(entry.get("env", {})),
    )


def _validate_exact_mcp_config(
    provider_id: str,
    project: Path,
    backend: HindsightBackendConfig,
) -> None:
    descriptor = get_descriptor(provider_id)
    assert descriptor is not None and descriptor.mcp_config is not None
    spec = descriptor.mcp_config
    config_path = spec.config_path(project) if callable(spec.config_path) else project / spec.config_path
    assert config_path.exists(), f"{provider_id}: MCP config missing at {config_path}"
    entries = spec.reader(config_path)
    assert backend.server_name in entries, f"{provider_id}: missing hindsight MCP entry"
    assert entries[backend.server_name] == _expected_mcp_entry(backend), (
        f"{provider_id}: wrong hindsight MCP entry in {config_path}"
    )


def _validate_rules_block(project: Path) -> None:
    rule_files = [p for p in project.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".mdx"}]
    matching = [p for p in rule_files if _RULE_MARKER in _read(p)]
    assert matching, "expected a managed Hindsight rule block"
    text = _read(matching[0])
    assert f"# >>> {_RULE_MARKER} >>>" in text
    assert f"# <<< {_RULE_MARKER} <<<" in text
    assert "Recall before design/history questions" in text
    assert "Do not retain secrets" in text


def _validate_hybrid_config(
    provider_id: str,
    project: Path,
    backend: HindsightBackendConfig,
) -> None:
    _validate_exact_mcp_config(provider_id, project, backend)
    _validate_rules_block(project)


def _validate_installer_artifacts(provider_id: str, home: Path) -> None:
    hindsight_dir = home / ".hindsight"
    assert hindsight_dir.exists(), f"{provider_id}: ~/.hindsight not created"
    if provider_id == "codex":
        hooks = home / ".codex" / "hooks.json"
        config = home / ".codex" / "config.toml"
        scripts = hindsight_dir / "codex" / "scripts"
        assert hooks.exists(), "codex: ~/.codex/hooks.json missing"
        assert config.exists(), "codex: ~/.codex/config.toml missing"
        assert scripts.exists(), "codex: hook scripts missing"
        hooks_text = hooks.read_text(encoding="utf-8")
        assert "session_start.py" in hooks_text
        assert "recall.py" in hooks_text
        assert "retain.py" in hooks_text
        assert "codex_hooks = true" in config.read_text(encoding="utf-8")
    elif provider_id == "cline":
        cfg = hindsight_dir / "cline.json"
        assert cfg.exists(), "cline: ~/.hindsight/cline.json missing"
        payload = json.loads(cfg.read_text(encoding="utf-8"))
        rendered = json.dumps(payload).lower()
        assert "hindsight" in rendered
        assert _NEEDLE in rendered


def _validate_plugin_artifacts(provider_id: str, home: Path) -> None:
    if provider_id != "claude":
        raise AssertionError(f"no plugin validator for {provider_id}")
    cache_roots = list((home / ".claude" / "plugins" / "cache").rglob("plugin.json"))
    assert cache_roots, "claude: no cached plugin manifest found"
    manifest_paths = [p for p in cache_roots if "hindsight-memory" in p.as_posix()]
    assert manifest_paths, "claude: hindsight plugin manifest missing"
    manifest = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
    assert manifest["name"] == "hindsight-memory"
    mcp_files = [p for p in manifest_paths[0].parents[1].rglob(".mcp.json")]
    assert mcp_files, "claude: plugin MCP config missing"
    mcp_text = mcp_files[0].read_text(encoding="utf-8")
    assert "hindsight" in mcp_text
    assert "run_mcp.sh" in mcp_text


@pytest.mark.parametrize("provider_id", sorted(_SPECS))
@pytest.mark.timeout(600)
def test_provider_hindsight_provisioning(provider_id, tmp_path, monkeypatch):
    kind, reason = _SPECS[provider_id]

    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.chdir(project)

    if provider_id in _PREINSTALL_PROVIDER_CLI:
        install_result = install_provider_cli(provider_id, timeout=300, project_root=project)
        assert install_result.get("status") == "installed", (
            f"{provider_id} CLI install failed: {install_result}"
        )

    backend = HindsightBackendConfig(base_url=_SERVER, api_key="e2e-token")
    try:
        result = apply_hindsight(project, backend=backend, provider_ids=[provider_id])[provider_id]
    finally:
        if provider_id in _PREINSTALL_PROVIDER_CLI:
            uninstall_provider_cli(provider_id, timeout=300, project_root=project)

    if kind == "expected-failure":
        assert result.success is False, f"{provider_id} unexpectedly provisioned"
        combined = " ".join(
            part for part in (result.error, result.status, result.action_needed) if part
        ).lower()
        assert combined, f"{provider_id}: expected actionable failure detail"
        for token in reason.lower().split():
            needle = token.strip("`()")
            if needle:
                assert needle in combined, (
                    f"{provider_id}: expected failure to mention {needle!r}, got {combined!r}"
                )
        return

    assert result.success, f"{provider_id} provisioning failed: {result.error}"
    assert result.state.value == "verified", f"{provider_id}: unexpected final state {result.state.value}"

    if kind == "success-mcp":
        _validate_exact_mcp_config(provider_id, project, backend)
    elif kind == "success-hybrid":
        _validate_hybrid_config(provider_id, project, backend)
    elif kind == "success-installer":
        _validate_installer_artifacts(provider_id, home)
    elif kind == "success-plugin":
        _validate_plugin_artifacts(provider_id, home)
    elif kind == "success-rules":
        _validate_rules_block(project)


def test_hindsight_e2e_specs_cover_all_matrix_providers():
    assert set(_SPECS) == {row.provider_id for row in HINDSIGHT_RECIPE_MATRIX}
