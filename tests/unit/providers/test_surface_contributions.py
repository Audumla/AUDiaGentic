from __future__ import annotations

from pathlib import Path

import audiagentic.interoperability.providers  # noqa: F401
from audiagentic.interoperability.providers.surfaces.base import (
    SurfaceBlock,
    apply_managed_blocks,
)
from audiagentic.interoperability.providers.surfaces.contributions import (
    load_surface_contributions,
)
from audiagentic.interoperability.providers.surfaces.manager import (
    apply_provider_surfaces,
    build_provider_surface_blocks,
    plan_provider_surfaces,
)


def test_loads_release_ledger_surface_contribution() -> None:
    contributions = load_surface_contributions()
    by_id = {item.contribution_id: item for item in contributions}

    contribution = by_id["release-audit-ledger.process"]
    assert contribution.owner_component == "release-audit-ledger"
    assert contribution.kind == "rule"
    assert "release audit ledger process" in contribution.title.lower()


def test_managed_block_replaces_existing_block_without_duplicate() -> None:
    block = SurfaceBlock(
        path=Path("AGENTS.md"),
        block_id="release-audit-ledger.process",
        content="## Release\n\nNew body",
    )
    first = apply_managed_blocks("User text\n", [block])
    second = apply_managed_blocks(first, [block])

    assert second.count("AUDIAGENTIC:BEGIN release-audit-ledger.process") == 1
    assert "New body" in second


def test_provider_surface_blocks_dedupe_shared_agents_file(tmp_path: Path) -> None:
    blocks = build_provider_surface_blocks(tmp_path)
    agents_blocks = [
        block for block in blocks
        if block.path == tmp_path / "AGENTS.md" and block.block_id == "release-audit-ledger.process"
    ]

    assert len(agents_blocks) == 1


def test_apply_provider_surfaces_writes_provider_owned_paths(tmp_path: Path) -> None:
    result = apply_provider_surfaces(tmp_path, provider_id="cline")
    target = tmp_path / ".clinerules" / "audiagentic.md"

    assert result["ok"] is True
    assert str(target) in result["written"]
    assert "release-audit-ledger.process" in target.read_text(encoding="utf-8")


def test_roo_provider_surface_owns_roo_rules_path(tmp_path: Path) -> None:
    result = apply_provider_surfaces(tmp_path, provider_id="roo")
    target = tmp_path / ".roo" / "rules" / "audiagentic.md"

    assert result["ok"] is True
    assert str(target) in result["written"]
    assert "release-audit-ledger.process" in target.read_text(encoding="utf-8")


def test_plan_provider_surfaces_reports_changes(tmp_path: Path) -> None:
    result = plan_provider_surfaces(tmp_path, provider_id="codex")

    assert result["ok"] is True
    assert result["files"][0]["changed"] is True
    block_ids = result["files"][0]["block-ids"]
    assert "release-audit-ledger.process" in block_ids
    assert "agent-jobs/canonical-rule" in block_ids
