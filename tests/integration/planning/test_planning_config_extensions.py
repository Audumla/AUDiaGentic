from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from audiagentic.planning.app.config import Config

PLANNING_CONFIG_SRC = ROOT / ".audiagentic" / "planning" / "config"


def _seed_config(tmp_path: Path) -> Path:
    dst = tmp_path / ".audiagentic" / "planning" / "config"
    dst.mkdir(parents=True, exist_ok=True)

    for f in PLANNING_CONFIG_SRC.glob("*.yaml"):
        shutil.copy(f, dst / f.name)

    profile_pack_src = PLANNING_CONFIG_SRC / "profile-packs"
    if profile_pack_src.exists():
        shutil.copytree(profile_pack_src, dst / "profile-packs")

    return tmp_path


def test_config_extensions_available_in_seeded_project(tmp_path: Path) -> None:
    root = _seed_config(tmp_path)
    cfg = Config(root)
    assert cfg.validate() == []
    assert cfg.documentation["planning"]["documentation"]["surfaces"]
    assert cfg.request_profiles["request_profiles"]["feature"]["label"] == "Feature request"
    assert cfg.profile_packs["standard"]["profile_pack"]["documentation"]["required_updates"]["task"] == ["changelog"]
