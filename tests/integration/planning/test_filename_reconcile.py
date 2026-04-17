"""Integration tests for canonical filename reconciliation (request-31)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from audiagentic.planning.app.api import PlanningAPI
from audiagentic.planning.app.paths import Paths
from audiagentic.planning.app.rec_mgr import Reconcile
from audiagentic.planning.fs.scan import scan_items

PLANNING_CONFIG_SRC = ROOT / ".audiagentic" / "planning" / "config"
DOCS_SRC = ROOT / "docs" / "planning"


def _seed_root(tmp_path: Path) -> Path:
    """Seed a minimal planning root with config and a couple of planning docs."""
    cfg_dst = tmp_path / ".audiagentic" / "planning" / "config"
    cfg_dst.mkdir(parents=True, exist_ok=True)
    for f in PLANNING_CONFIG_SRC.glob("*.yaml"):
        shutil.copy(f, cfg_dst / f.name)
    pack_src = PLANNING_CONFIG_SRC / "profile-packs"
    if pack_src.exists():
        shutil.copytree(pack_src, cfg_dst / "profile-packs")

    # Copy a small subset of real planning docs for integration coverage
    for kind_dir in ["requests", "specifications"]:
        src = DOCS_SRC / kind_dir
        if src.exists():
            dst = tmp_path / "docs" / "planning" / kind_dir
            shutil.copytree(src, dst)

    return tmp_path


def _write_item(root: Path, kind_dir: str, filename: str, id_: str, label: str) -> Path:
    """Write a planning item with mismatched filename (bare ID, no slug)."""
    kind_path = root / "docs" / "planning" / kind_dir
    kind_path.mkdir(parents=True, exist_ok=True)
    path = kind_path / filename
    path.write_text(
        f"---\nid: {id_}\nlabel: {label}\nstate: draft\nsummary: test item\n---\n\n# Body\n",
        encoding="utf-8",
    )
    return path


# --- Paths.filename_for tests ---

def test_filename_for_includes_slug(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    paths = Paths(root)
    name = paths.filename_for("request", "request-42", "My Feature Request")
    assert name == "request-42-my-feature-request.md"


def test_filename_for_bare_id_no_slug(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    paths = Paths(root)
    # Bare label still produces slug (empty slug → just id)
    name = paths.filename_for("request", "request-1", "A")
    assert name.startswith("request-1-")
    assert name.endswith(".md")


def test_filename_for_spec_with_slug(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    paths = Paths(root)
    name = paths.filename_for("spec", "spec-007", "Index Backed Lookup")
    assert name == "spec-007-index-backed-lookup.md"


# --- Reconcile.run() tests ---

def test_reconcile_renames_bare_id_file(tmp_path: Path) -> None:
    """File named just {id}.md should be renamed to {id}-{slug}.md."""
    root = _seed_root(tmp_path)
    bare = _write_item(root, "requests", "request-99.md", "request-99", "My New Feature")

    rec = Reconcile(root)
    result = rec.run()

    assert any(r["id"] == "request-99" for r in result["renames"]), result["renames"]
    renamed = root / "docs" / "planning" / "requests" / "request-99-my-new-feature.md"
    assert renamed.exists()
    assert not bare.exists()


def test_reconcile_returns_rename_details(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    _write_item(root, "requests", "request-88.md", "request-88", "Search Enhancement")

    rec = Reconcile(root)
    result = rec.run()

    rename = next((r for r in result["renames"] if r["id"] == "request-88"), None)
    assert rename is not None
    assert rename["from"] == "request-88.md"
    assert rename["to"] == "request-88-search-enhancement.md"


def test_reconcile_no_rename_when_canonical(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    # Write file already in canonical form
    _write_item(root, "requests", "request-77-already-canonical.md", "request-77", "Already Canonical")

    rec = Reconcile(root)
    result = rec.run()

    assert not any(r["id"] == "request-77" for r in result["renames"])


def test_reconcile_result_has_orphans_key(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    rec = Reconcile(root)
    result = rec.run()
    assert "renames" in result
    assert "orphans" in result
    assert isinstance(result["renames"], list)
    assert isinstance(result["orphans"], list)


# --- API maintain / clean_indexes tests ---

def test_maintain_returns_renames_and_rebuild_summary(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    _write_item(root, "requests", "request-66.md", "request-66", "Maintain Test")

    api = PlanningAPI(root)
    result = api.maintain()

    assert "renames" in result
    assert "indexes_rebuilt" in result
    assert "extracts_rebuilt" in result
    assert any(r["id"] == "request-66" for r in result["renames"])


def test_clean_indexes_rebuilds_indexes(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    api = PlanningAPI(root)
    result = api.clean_indexes()
    assert result["indexes_rebuilt"] is True
    idx_dir = root / ".audiagentic" / "planning" / "indexes"
    assert idx_dir.exists()
    assert any(idx_dir.iterdir())


def test_clean_indexes_does_not_rename_files(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    bare = _write_item(root, "requests", "request-55.md", "request-55", "No Rename Test")

    api = PlanningAPI(root)
    api.clean_indexes()

    # File should NOT be renamed — clean_indexes doesn't reconcile filenames
    assert bare.exists(), "clean_indexes must not rename files"


def test_zero_mismatches_after_maintain(tmp_path: Path) -> None:
    """After maintain, all files should have canonical filenames."""
    root = _seed_root(tmp_path)
    # Introduce mismatches
    _write_item(root, "requests", "request-44.md", "request-44", "Mismatch One")
    _write_item(root, "requests", "request-45.md", "request-45", "Mismatch Two")

    api = PlanningAPI(root)
    api.maintain()

    paths = Paths(root)
    items = scan_items(root)
    mismatches = [
        i for i in items
        if paths.filename_for(i.kind, i.data["id"], i.data["label"]) != i.path.name
    ]
    assert mismatches == [], f"Unexpected mismatches after maintain: {mismatches}"


# --- Naming config tests ---

def test_naming_config_defines_slug_policy(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    cfg = yaml.safe_load((root / ".audiagentic/planning/config/planning.yaml").read_text())
    naming = cfg["planning"]["naming"]
    assert naming["slug_policy"] == "always"
    assert "{id}" in naming["default_pattern"]
    assert "{slug}" in naming["default_pattern"]


def test_naming_config_defines_numeric_format(tmp_path: Path) -> None:
    root = _seed_root(tmp_path)
    cfg = yaml.safe_load((root / ".audiagentic/planning/config/planning.yaml").read_text())
    naming = cfg["planning"]["naming"]
    assert "numeric_format" in naming
