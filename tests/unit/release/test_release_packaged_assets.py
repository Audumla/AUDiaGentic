from __future__ import annotations

from pathlib import Path

from audiagentic.components.release.release_please.manage import _render_baseline


def test_packaged_release_workflow_asset_matches_default_baseline() -> None:
    root = Path(__file__).resolve().parents[3]
    asset = root / "src" / "audiagentic" / "config" / "components" / "release" / ".github" / "workflows" / "release.yml"

    assert asset.read_text(encoding="utf-8") == _render_baseline()
