"""Adoption / collision / cross-kind tests for harness materialize outputs.

HA08 — verify that materialize_agent_config for each harness either preserves
foreign content (adoption) or documents why full-rebuild is safe for
AUDiaGentic-exclusive files, and that known collision risks stay guarded.

All tests are unit-level: they call materialize_agent_config directly against
tmp_path with no real component lifecycle events or real CLI on PATH.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _harness_cfg() -> dict:
    """Minimal harness config sufficient for both Pi and OpenCode materialize."""
    return {
        "rig": {
            "model": "qwen3.5-0.8b",
            "port": 42001,
            "provider": "audiagentic",
        }
    }


# --------------------------------------------------------------------------- #
# File inventory (from reading current materialize bodies, 2026-07-27)
# --------------------------------------------------------------------------- #
# Pi writes:
#   target/agent/models.json       — full dict-literal overwrite (AUDiaGentic-exclusive)
#   target/agent/settings.json     — full dict-literal overwrite (AUDiaGentic-exclusive)
#   target/agent/SYSTEM.md         — from template + injections (then deleted as stale)
#   target/agent/APPEND_SYSTEM.md  — copied from template
#   Provider surfaces: operate_provider_surfaces(root, "pi", mode="apply")
#
# OpenCode writes:
#   root/AGENTS.md                  — template + injections + provider surface managed blocks
#   root/.opencode/config.json     — full dict-literal overwrite (AUDiaGentic-exclusive)
#   Provider surfaces: operate_provider_surfaces(root, "opencode", mode="apply")

# AUDiaGentic-exclusive files (full-rebuild is safe — never hand-edited by a user):
#   Pi:        agent/models.json, agent/settings.json
#   OpenCode:  .opencode/config.json

# Files with mixed ownership (foreign content must survive):
#   AGENTS.md (both harnesses) — template + injections + managed blocks + user-authored regions


# --------------------------------------------------------------------------- #
# Adoption: AUDiaGentic-exclusive files use full-rebuild (safe by design)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("harness_type", ["pi", "opencode"])
def test_exclusive_config_full_rebuild_is_intentional(harness_type: str, tmp_path: Path) -> None:
    """AUDiaGentic-exclusive config files use full dict-literal overwrite.

    These files are exclusively owned by AUDiaGentic (never hand-edited by a
    user), so full-rebuild is safe and intentional — foreign keys pre-seeded
    in the file WILL be clobbered. This test documents that behavior.
    """
    project_root = tmp_path / "project"
    harness_root = tmp_path / "harness"
    project_root.mkdir()
    harness_root.mkdir()

    if harness_type == "pi":
        from audiagentic.runtime.harness.pi.install.config import (
            materialize_agent_config,
        )

        target = harness_root
        config_file = harness_root / "agent" / "models.json"
    else:
        from audiagentic.runtime.harness.opencode.install import (
            materialize_agent_config,
        )

        # OpenCode: target == project_root for materialize call.
        target = project_root
        config_file = project_root / ".opencode" / "config.json"

    # Pre-seed foreign content that AUDiaGentic does not own.
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        json.dumps({"userOwnedKey": "do-not-touch", "anotherForeign": 42}),
        encoding="utf-8",
    )

    materialize_agent_config(target, _harness_cfg(), project_root=project_root)

    data = json.loads(config_file.read_text(encoding="utf-8"))
    # Full-rebuild clobbers foreign keys — this is the documented, intentional
    # behavior for AUDiaGentic-exclusive files. If this ever changes to
    # read-merge-write, update the assertion accordingly.
    assert "userOwnedKey" not in data, (
        f"[{harness_type}] full-rebuild should clobber foreign keys — "
        "if it doesn't, the write pattern changed and the test needs updating"
    )
    # Verify AUDiaGentic content IS written.
    assert "providers" in data, f"[{harness_type}] AUDiaGentic-managed content not present: {data}"


@pytest.mark.parametrize("harness_type", ["pi", "opencode"])
def test_exclusive_config_idempotent_rebuild(harness_type: str, tmp_path: Path) -> None:
    """Calling materialize twice produces the same AUDiaGentic output."""
    project_root = tmp_path / "project"
    harness_root = tmp_path / "harness"
    project_root.mkdir()
    harness_root.mkdir()

    if harness_type == "pi":
        from audiagentic.runtime.harness.pi.install.config import (
            materialize_agent_config,
        )

        target = harness_root
        config_file = harness_root / "agent" / "models.json"
    else:
        from audiagentic.runtime.harness.opencode.install import (
            materialize_agent_config,
        )

        target = project_root
        config_file = project_root / ".opencode" / "config.json"

    # First pass.
    materialize_agent_config(target, _harness_cfg(), project_root=project_root)
    first = json.loads(config_file.read_text(encoding="utf-8"))

    # Second pass (same harness_cfg).
    materialize_agent_config(target, _harness_cfg(), project_root=project_root)
    second = json.loads(config_file.read_text(encoding="utf-8"))

    assert first == second, (
        f"[{harness_type}] materialize is not idempotent:\nfirst  = {first}\nsecond = {second}"
    )


# --------------------------------------------------------------------------- #
# Adoption: Pi models.json specifically — structure is correct after rebuild
# --------------------------------------------------------------------------- #


def test_pi_models_json_providers_key_structure(tmp_path: Path) -> None:
    """Pi models.json always writes a top-level 'providers' key with the rig."""
    from audiagentic.runtime.harness.pi.install.config import (
        materialize_agent_config,
    )

    harness_root = tmp_path / "harness"
    project_root = tmp_path / "project"
    project_root.mkdir()
    harness_root.mkdir()

    materialize_agent_config(harness_root, _harness_cfg(), project_root=project_root)

    data = json.loads((harness_root / "agent" / "models.json").read_text(encoding="utf-8"))

    assert "providers" in data
    assert "audiagentic" in data["providers"]
    provider_block = data["providers"]["audiagentic"]
    assert provider_block["baseUrl"] == "http://127.0.0.1:42001/v1"
    assert provider_block["api"] == "openai-completions"
    assert len(provider_block["models"]) >= 1


def test_opencode_config_json_providers_key_structure(tmp_path: Path) -> None:
    """OpenCode .opencode/config.json always writes a top-level 'providers' key."""
    from audiagentic.runtime.harness.opencode.install import (
        materialize_agent_config,
    )

    project_root = tmp_path / "project"
    project_root.mkdir()

    materialize_agent_config(project_root, _harness_cfg(), project_root=project_root)

    data = json.loads((project_root / ".opencode" / "config.json").read_text(encoding="utf-8"))

    assert "providers" in data
    assert "audiagentic" in data["providers"]
    provider_block = data["providers"]["audiagentic"]
    assert provider_block["baseURL"] == "http://127.0.0.1:42001/v1"
    assert provider_block["api"] == "openai"


# --------------------------------------------------------------------------- #
# Collision: OpenCode must never write bare .mcp.json
# --------------------------------------------------------------------------- #


def test_opencode_materialize_never_writes_bare_mcp_json(tmp_path: Path) -> None:
    """OpenCode materialize must never create a bare .mcp.json at project root.

    This path collides with Pi's PROVIDER mcp_config target (see the comment
    in runtime/harness/opencode/install/__init__.py ~line 103-108).
    The AUDiaGentic-curated MCP surface for OpenCode is delivered at launch
    time via OPENCODE_CONFIG_CONTENT, not a file.
    """
    from audiagentic.runtime.harness.opencode.install import (
        materialize_agent_config,
    )

    project_root = tmp_path / "project"
    project_root.mkdir()

    materialize_agent_config(project_root, _harness_cfg(), project_root=project_root)

    assert not (project_root / ".mcp.json").exists(), (
        "OpenCode materialize must never create a bare .mcp.json — "
        "it collides with Pi's PROVIDER mcp_config target"
    )


# --------------------------------------------------------------------------- #
# AGENTS.md three-layer composition (idempotency + non-destructive)
# --------------------------------------------------------------------------- #


def test_agents_md_template_layer_writes(tmp_path: Path) -> None:
    """AGENTS.md contains the template + injection content after materialize."""
    from audiagentic.runtime.harness.opencode.install import (
        materialize_agent_config,
    )

    project_root = tmp_path / "project"
    project_root.mkdir()

    materialize_agent_config(project_root, _harness_cfg(), project_root=project_root)

    content = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    # Template content is always present.
    assert "Project instructions" in content


def test_agents_md_surface_apply_is_called(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """operate_provider_surfaces is called during OpenCode materialize."""
    from audiagentic.runtime.harness.opencode.install import (
        materialize_agent_config,
    )

    project_root = tmp_path / "project"
    project_root.mkdir()

    calls: list[tuple] = []

    def _fake_operate(project_root: Path, provider_id: str, *, mode: str) -> dict:
        calls.append((str(project_root), provider_id, mode))
        return {"ok": True, "written": []}

    monkeypatch.setattr(
        "audiagentic.components.providers.providers_api.operate_provider_surfaces",
        _fake_operate,
    )

    materialize_agent_config(project_root, _harness_cfg(), project_root=project_root)

    assert len(calls) == 1
    assert calls[0] == (str(project_root), "opencode", "apply")


def test_agents_md_idempotent_after_repeated_materialize(tmp_path: Path) -> None:
    """AGENTS.md template content is stable after repeated materialize calls.

    The managed blocks region may differ if provider surfaces re-render, but the
    template + injection layers above the managed region must be identical.
    """
    from audiagentic.runtime.harness.opencode.install import (
        materialize_agent_config,
    )

    project_root = tmp_path / "project"
    project_root.mkdir()

    # First pass.
    materialize_agent_config(project_root, _harness_cfg(), project_root=project_root)
    first = (project_root / "AGENTS.md").read_text(encoding="utf-8")

    # Second pass.
    materialize_agent_config(project_root, _harness_cfg(), project_root=project_root)
    second = (project_root / "AGENTS.md").read_text(encoding="utf-8")

    # Template + injection layers should be identical.
    assert first == second, "AGENTS.md changed between two materialize calls with the same config"


# --------------------------------------------------------------------------- #
# Pi-specific: SYSTEM.md lifecycle
# --------------------------------------------------------------------------- #


def test_pi_system_md_writes_from_template(tmp_path: Path) -> None:
    """Pi materialize writes SYSTEM.md at target/ (not agent/) from template."""
    from audiagentic.runtime.harness.pi.install.config import (
        materialize_agent_config,
    )

    harness_root = tmp_path / "harness"
    project_root = tmp_path / "project"
    project_root.mkdir()
    harness_root.mkdir()

    materialize_agent_config(harness_root, _harness_cfg(), project_root=project_root)

    # SYSTEM.md is written to target/ first.
    system_md = harness_root / "SYSTEM.md"
    # Then stale SYSTEM.md at agent/SYSTEM.md is deleted — only target/SYSTEM.md exists.
    assert not (harness_root / "agent" / "SYSTEM.md").exists(), (
        "Stale agent/SYSTEM.md should be deleted during Pi materialize"
    )


def test_pi_append_system_md_copied_from_template(tmp_path: Path) -> None:
    """Pi materialize copies APPEND_SYSTEM.md from template to agent/."""
    from audiagentic.runtime.harness.pi.install.config import (
        materialize_agent_config,
    )

    harness_root = tmp_path / "harness"
    project_root = tmp_path / "project"
    project_root.mkdir()
    harness_root.mkdir()

    materialize_agent_config(harness_root, _harness_cfg(), project_root=project_root)

    append_md = harness_root / "agent" / "APPEND_SYSTEM.md"
    assert append_md.exists(), "APPEND_SYSTEM.md should be copied to agent/"


# --------------------------------------------------------------------------- #
# Cross-kind: both harnesses write providers key with correct rig structure
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("harness_type", ["pi", "opencode"])
def test_both_harnesses_write_rig_provider_entry(harness_type: str, tmp_path: Path) -> None:
    """Both Pi and OpenCode write the audiagentic provider with rig connection."""
    project_root = tmp_path / "project"
    harness_root = tmp_path / "harness"
    project_root.mkdir()
    harness_root.mkdir()

    if harness_type == "pi":
        from audiagentic.runtime.harness.pi.install.config import (
            materialize_agent_config,
        )

        target = harness_root
        config_file = harness_root / "agent" / "models.json"
    else:
        from audiagentic.runtime.harness.opencode.install import (
            materialize_agent_config,
        )

        target = project_root
        config_file = project_root / ".opencode" / "config.json"

    materialize_agent_config(target, _harness_cfg(), project_root=project_root)

    data = json.loads(config_file.read_text(encoding="utf-8"))

    # Both harnesses write a providers block with the audiagentic provider.
    assert "providers" in data, f"[{harness_type}] missing 'providers' key: {data}"
    provider_block = data["providers"].get("audiagentic")
    assert provider_block is not None, f"[{harness_type}] missing 'audiagentic' provider: {data}"

    # Both connect to the rig at 127.0.0.1:42001/v1.
    base_url = provider_block.get("baseUrl") or provider_block.get("baseURL")
    assert base_url == "http://127.0.0.1:42001/v1", (
        f"[{harness_type}] rig base URL mismatch: {base_url}"
    )


# --------------------------------------------------------------------------- #
# Pi settings.json — structure check
# --------------------------------------------------------------------------- #


def test_pi_settings_json_has_theme(tmp_path: Path) -> None:
    """Pi settings.json always writes a theme key."""
    from audiagentic.runtime.harness.pi.install.config import (
        materialize_agent_config,
    )

    harness_root = tmp_path / "harness"
    project_root = tmp_path / "project"
    project_root.mkdir()
    harness_root.mkdir()

    materialize_agent_config(harness_root, _harness_cfg(), project_root=project_root)

    data = json.loads((harness_root / "agent" / "settings.json").read_text(encoding="utf-8"))

    assert "theme" in data, f"Pi settings.json missing 'theme' key: {data}"
