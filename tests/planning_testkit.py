from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_PLANNING_CONFIG_SRC = ROOT / "tests" / "fixtures" / "planning_config"


def seed_planning_config(
    root: Path,
    *,
    include_optional: bool = True,
    include_profile_packs: bool = True,
    include_templates: bool = True,
) -> Path:
    """Seed isolated planning config from test fixture snapshot, not prod config."""
    dst = root / ".audiagentic" / "planning" / "config"
    dst.mkdir(parents=True, exist_ok=True)
    indexes_dir = root / ".audiagentic" / "planning" / "indexes"
    indexes_dir.mkdir(parents=True, exist_ok=True)

    required = (
        "planning.yaml",
        "profiles.yaml",
        "workflows.yaml",
        "automations.yaml",
    )
    for name in required:
        shutil.copy(TEST_PLANNING_CONFIG_SRC / name, dst / name)

    if include_optional:
        for name in ("documentation.yaml", "state_propagation.yaml"):
            src = TEST_PLANNING_CONFIG_SRC / name
            if src.exists():
                shutil.copy(src, dst / name)

    if include_profile_packs:
        src = TEST_PLANNING_CONFIG_SRC / "profile-packs"
        if src.exists():
            shutil.copytree(src, dst / "profile-packs", dirs_exist_ok=True)

    if include_templates:
        src = TEST_PLANNING_CONFIG_SRC / "templates"
        if src.exists():
            shutil.copytree(src, dst / "templates", dirs_exist_ok=True)

    lookup_index = indexes_dir / "lookup.json"
    if not lookup_index.exists():
        lookup_index.write_text("{}", encoding="utf-8")

    return dst
