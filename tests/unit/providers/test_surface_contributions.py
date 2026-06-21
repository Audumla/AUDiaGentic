from __future__ import annotations

from pathlib import Path

import audiagentic.components.optional.providers  # noqa: F401
from audiagentic.components.optional.providers.surfaces.base import (
    MANAGED_REGION_BEGIN,
    MANAGED_REGION_END,
    SurfaceBlock,
    apply_managed_blocks,
)
from audiagentic.components.optional.providers.surfaces.contributions import (
    load_surface_contributions,
)
from audiagentic.components.optional.providers.surfaces.manager import (
    apply_provider_surfaces,
    build_provider_surface_blocks,
    plan_provider_surfaces,
    prune_provider_surfaces,
)


def _install_agent_ledger(tmp_path: Path) -> None:
    marker = tmp_path / ".audiagentic" / "components" / "agent-ledger.yaml"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("installed: true\n", encoding="utf-8")


def _enable_provider(tmp_path: Path, *provider_ids: str) -> None:
    """Enable providers so enabled-aware surface projection targets them."""
    from audiagentic.components.optional.providers.services.provider_config import (
        set_provider_enabled,
    )

    for provider_id in provider_ids:
        set_provider_enabled(tmp_path, provider_id, enabled=True)


def test_loads_release_ledger_surface_contribution() -> None:
    contributions = load_surface_contributions()
    by_id = {item.contribution_id: item for item in contributions}

    contribution = by_id["agent-ledger/process"]
    assert contribution.owner_component == "agent-ledger"
    assert "agent ledger process" in contribution.title.lower()


def test_managed_region_replaces_without_duplicate() -> None:
    block = SurfaceBlock(
        path=Path("AGENTS.md"),
        block_id="agent-ledger/process",
        content="## Release\n\nNew body",
    )
    first = apply_managed_blocks("User text\n", [block])
    second = apply_managed_blocks(first, [block])

    # exactly one managed region, user content preserved, no legacy fences
    assert second.count(MANAGED_REGION_BEGIN) == 1
    assert second.count(MANAGED_REGION_END) == 1
    assert "User text" in second
    assert "New body" in second
    assert "AUDIAGENTIC:BEGIN" not in second


def test_apply_empty_blocks_removes_region_keeps_user_text() -> None:
    block = SurfaceBlock(path=Path("AGENTS.md"), block_id="x/y", content="## X\n\nbody")
    applied = apply_managed_blocks("User text\n", [block])
    cleared = apply_managed_blocks(applied, [])

    assert MANAGED_REGION_BEGIN not in cleared
    assert "body" not in cleared
    assert "User text" in cleared


def test_apply_migrates_legacy_per_block_fences() -> None:
    legacy = (
        "User text\n\n"
        "<!-- AUDIAGENTIC:BEGIN old/a -->\n## Old A\n\nstale\n<!-- AUDIAGENTIC:END old/a -->\n"
    )
    block = SurfaceBlock(path=Path("AGENTS.md"), block_id="new/b", content="## New B\n\nfresh")
    result = apply_managed_blocks(legacy, [block])

    assert "AUDIAGENTIC:BEGIN" not in result   # legacy fence migrated away
    assert "stale" not in result
    assert "fresh" in result
    assert result.count(MANAGED_REGION_BEGIN) == 1
    assert "User text" in result


def test_provider_surface_blocks_dedupe_shared_agents_file(tmp_path: Path) -> None:
    _install_agent_ledger(tmp_path)
    # Two enabled providers share AGENTS.md; the block must still dedupe to one.
    _enable_provider(tmp_path, "codex", "opencode")
    blocks = build_provider_surface_blocks(tmp_path)
    agents_blocks = [
        block for block in blocks
        if block.path == tmp_path / "AGENTS.md" and block.block_id == "agent-ledger/process"
    ]

    assert len(agents_blocks) == 1


def test_apply_provider_surfaces_writes_provider_owned_paths(tmp_path: Path) -> None:
    _install_agent_ledger(tmp_path)
    result = apply_provider_surfaces(tmp_path, provider_id="cline")
    target = tmp_path / ".clinerules" / "audiagentic.md"

    assert result["ok"] is True
    assert str(target) in result["written"]
    # block_id is no longer emitted into the file; the friendly title is
    assert "Agent ledger process" in target.read_text(encoding="utf-8")


def test_roo_provider_surface_owns_roo_rules_path(tmp_path: Path) -> None:
    _install_agent_ledger(tmp_path)
    result = apply_provider_surfaces(tmp_path, provider_id="roo")
    target = tmp_path / ".roo" / "rules" / "audiagentic.md"

    assert result["ok"] is True
    assert str(target) in result["written"]
    assert "Agent ledger process" in target.read_text(encoding="utf-8")


def test_plan_provider_surfaces_reports_changes(tmp_path: Path) -> None:
    _install_agent_ledger(tmp_path)
    result = plan_provider_surfaces(tmp_path, provider_id="codex")

    assert result["ok"] is True
    assert result["files"][0]["changed"] is True
    block_ids = result["files"][0]["block-ids"]
    assert "agent-ledger/process" in block_ids


def test_prune_provider_surfaces_removes_legacy_blocks(tmp_path: Path) -> None:
    _install_agent_ledger(tmp_path)
    _enable_provider(tmp_path, "cline")
    apply_provider_surfaces(tmp_path, provider_id="cline")
    target = tmp_path / ".clinerules" / "audiagentic.md"
    assert target.exists()
    content_before = target.read_text(encoding="utf-8")
    assert MANAGED_REGION_BEGIN in content_before

    # Inject a stale legacy-format block (pre-region layout)
    stale = (
        "\n\n<!-- AUDIAGENTIC:BEGIN stale-block -->\n"
        "Stale content\n"
        "<!-- AUDIAGENTIC:END stale-block -->\n"
    )
    target.write_text(content_before + stale, encoding="utf-8")

    # Prune regenerates the region and migrates away legacy fences
    result = prune_provider_surfaces(tmp_path, provider_id="cline")

    assert result["ok"] is True
    assert str(target) in result["pruned"]
    pruned_text = target.read_text(encoding="utf-8")
    assert "AUDIAGENTIC:BEGIN" not in pruned_text
    assert "Stale content" not in pruned_text
    assert pruned_text.count(MANAGED_REGION_BEGIN) == 1


def test_prune_provider_surfaces_leaves_active_blocks(tmp_path: Path) -> None:
    _install_agent_ledger(tmp_path)
    _enable_provider(tmp_path, "cline")
    apply_provider_surfaces(tmp_path, provider_id="cline")
    target = tmp_path / ".clinerules" / "audiagentic.md"
    content_before = target.read_text(encoding="utf-8")

    result = prune_provider_surfaces(tmp_path, provider_id="cline")

    # No stale blocks — nothing should be rewritten
    assert result["ok"] is True
    assert result["pruned"] == []
    assert target.read_text(encoding="utf-8") == content_before
