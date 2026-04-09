from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from audiagentic.planning.app.config import Config


def _seed_base_config(tmp_path: Path, include_optional: bool) -> Path:
    src = ROOT / ".audiagentic" / "planning" / "config"
    dst = tmp_path / ".audiagentic" / "planning" / "config"
    dst.mkdir(parents=True, exist_ok=True)

    for name in (
        "planning.yaml",
        "profiles.yaml",
        "workflows.yaml",
        "automations.yaml",
        "hooks.yaml",
    ):
        shutil.copy(src / name, dst / name)

    if include_optional:
        shutil.copy(src / "documentation.yaml", dst / "documentation.yaml")
        shutil.copy(src / "request-profiles.yaml", dst / "request-profiles.yaml")
        shutil.copytree(src / "profile-packs", dst / "profile-packs")

    return tmp_path


def test_config_optional_files_may_be_absent(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=False)
    cfg = Config(root)
    assert cfg.documentation == {}
    assert cfg.request_profiles == {}
    assert cfg.profile_packs == {}
    assert cfg.validate() == []


def test_config_loads_optional_files_when_present(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    assert cfg.documentation["planning"]["documentation"]["enabled"] is True
    assert "feature" in cfg.request_profiles["request_profiles"]
    assert "standard" in cfg.profile_packs
    assert cfg.profile_packs["standard"]["profile_pack"]["id"] == "standard"


def test_config_validates_optional_files_when_present(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    assert cfg.validate() == []

