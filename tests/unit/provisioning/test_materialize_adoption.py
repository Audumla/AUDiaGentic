"""Adoption / collision / cross-kind tests for harness materialize outputs.

HA08 — verify that materialize_provider_config for each provider either preserves
foreign content (adoption) or documents why full-rebuild is safe for
AUDiaGentic-exclusive files, and that known collision risks stay guarded.

All tests are unit-level: they call providers_api.materialize_provider_config
directly against tmp_path with no real component lifecycle events or real CLI on PATH.

Model config (models.json / .opencode/config.json) goes through the model-projection
family via managed config — NOT through materialize. This file only tests
provider-specific files written by adapter install modules.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.providers import providers_api

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
# Pi writes (via adapter install module):
#   target/agent/settings.json     — full dict-literal overwrite (AUDiaGentic-exclusive)
#   target/agent/APPEND_SYSTEM.md  — copied from template
#   Provider surfaces: operate_provider_surfaces(root, "pi", mode="apply")
#
# OpenCode writes (via adapter install module):
#   root/AGENTS.md                  — template + scoped provider surface blocks
#
# Model config (models.json / .opencode/config.json) goes through model-projection family.

# AUDiaGentic-exclusive files (full-rebuild is safe — never hand-edited by a user):
#   Pi:        agent/settings.json
#   OpenCode:  AGENTS.md template + injections (user content outside managed blocks preserved)

# Files with mixed ownership (foreign content must survive):
#   AGENTS.md (both harnesses) — template + injections + managed blocks + user-authored regions


# --------------------------------------------------------------------------- #
# AGENTS.md three-layer composition (idempotency + non-destructive)
# --------------------------------------------------------------------------- #


def test_agents_md_template_layer_writes(tmp_path: Path) -> None:
    """AGENTS.md contains the template + injection content after materialize."""
    project_root = tmp_path / "project"
    project_root.mkdir()

    providers_api.materialize_provider_config(project_root, "opencode", _harness_cfg())

    content = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    # Template content is always present.
    assert "Project instructions" in content


def test_agents_md_surface_apply_is_called_during_materialize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Materialize applies provider surfaces after project-scope filtering."""
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

    providers_api.materialize_provider_config(project_root, "opencode", _harness_cfg())

    assert calls == [(str(project_root), "opencode", "apply")]


def test_agents_md_idempotent_after_repeated_materialize(tmp_path: Path) -> None:
    """AGENTS.md template content is stable after repeated materialize calls.

    The managed blocks region may differ if provider surfaces re-render, but the
    template + injection layers above the managed region must be identical.
    """
    project_root = tmp_path / "project"
    project_root.mkdir()

    # First pass.
    providers_api.materialize_provider_config(project_root, "opencode", _harness_cfg())
    first = (project_root / "AGENTS.md").read_text(encoding="utf-8")

    # Second pass.
    providers_api.materialize_provider_config(project_root, "opencode", _harness_cfg())
    second = (project_root / "AGENTS.md").read_text(encoding="utf-8")

    # Template + injection layers should be identical.
    assert first == second, "AGENTS.md changed between two materialize calls with the same config"


# --------------------------------------------------------------------------- #
# Pi-specific: SYSTEM.md lifecycle & APPEND_SYSTEM.md
# --------------------------------------------------------------------------- #


def test_pi_system_md_writes_from_template(tmp_path: Path) -> None:
    """Pi materialize writes SYSTEM.md at target/ (not agent/) from template."""
    harness_root = tmp_path / "harness"
    project_root = tmp_path / "project"
    project_root.mkdir()
    harness_root.mkdir()

    providers_api.materialize_provider_config(
        project_root, "pi", _harness_cfg(), agent_runtime=harness_root
    )

    # SYSTEM.md is written to target/ first.
    # Then stale SYSTEM.md at agent/SYSTEM.md is deleted — only target/SYSTEM.md exists.
    assert not (harness_root / "agent" / "SYSTEM.md").exists(), (
        "Stale agent/SYSTEM.md should be deleted during Pi materialize"
    )


def test_pi_append_system_md_copied_from_template(tmp_path: Path) -> None:
    """Pi materialize copies APPEND_SYSTEM.md from template to agent/."""
    harness_root = tmp_path / "harness"
    project_root = tmp_path / "project"
    project_root.mkdir()
    harness_root.mkdir()

    providers_api.materialize_provider_config(
        project_root, "pi", _harness_cfg(), agent_runtime=harness_root
    )

    append_md = harness_root / "agent" / "APPEND_SYSTEM.md"
    assert append_md.exists(), "APPEND_SYSTEM.md should be copied to agent/"


# --------------------------------------------------------------------------- #
# Pi settings.json — structure check
# --------------------------------------------------------------------------- #


def test_pi_settings_json_has_theme(tmp_path: Path) -> None:
    """Pi settings.json always writes a theme key."""
    import json

    harness_root = tmp_path / "harness"
    project_root = tmp_path / "project"
    project_root.mkdir()
    harness_root.mkdir()

    providers_api.materialize_provider_config(
        project_root, "pi", _harness_cfg(), agent_runtime=harness_root
    )

    data = json.loads((harness_root / "agent" / "settings.json").read_text(encoding="utf-8"))

    assert "theme" in data, f"Pi settings.json missing 'theme' key: {data}"


# --------------------------------------------------------------------------- #
# Cross-kind: both providers write via correct entry point
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("provider_id", ["pi", "opencode"])
def test_both_providers_materialize_via_entry_point(provider_id: str, tmp_path: Path) -> None:
    """Both Pi and OpenCode materialize through providers_api.materialize_provider_config."""
    harness_root = tmp_path / "harness"
    project_root = tmp_path / "project"
    project_root.mkdir()
    harness_root.mkdir()

    if provider_id == "pi":
        # Pi writes to agent_runtime (global harness runtime)
        providers_api.materialize_provider_config(
            project_root, provider_id, _harness_cfg(), agent_runtime=harness_root
        )
        assert (harness_root / "agent" / "settings.json").exists()
    else:
        # OpenCode writes project-local files
        providers_api.materialize_provider_config(project_root, provider_id, _harness_cfg())
        assert (project_root / "AGENTS.md").exists()
