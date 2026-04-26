from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.planning_testkit import seed_planning_config

from audiagentic.planning.app.config import Config


def _seed_config(tmp_path: Path) -> Path:
    seed_planning_config(tmp_path)
    return tmp_path


def test_config_extensions_available_in_seeded_project(tmp_path: Path) -> None:
    root = _seed_config(tmp_path)
    cfg = Config(root)
    assert cfg.validate() == []
    assert cfg.documentation["planning"]["documentation"]["surfaces"]
    assert cfg.creation_profile_for("feature")["label"] == "Feature request"
    assert cfg.profile_packs["standard"]["profile_pack"]["documentation"]["required_updates"]["task"] == ["changelog"]
