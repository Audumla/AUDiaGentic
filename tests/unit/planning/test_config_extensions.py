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
    ):
        shutil.copy(src / name, dst / name)

    if include_optional:
        shutil.copy(src / "documentation.yaml", dst / "documentation.yaml")
        shutil.copytree(src / "profile-packs", dst / "profile-packs")

    return tmp_path


def test_config_optional_files_may_be_absent(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=False)
    cfg = Config(root)
    assert cfg.documentation == {}
    assert "request_profiles" in cfg.request_profiles
    assert cfg.request_profiles["request_profiles"] != {}
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


def test_guidance_levels_exist(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    levels = cfg.guidance_levels()
    assert "light" in levels
    assert "standard" in levels
    assert "deep" in levels


def test_guidance_level_semantics(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    for level in ["light", "standard", "deep"]:
        level_config = cfg.guidance_for(level)
        assert "description" in level_config
        assert "label" in level_config
        assert "defaults" in level_config
        assert "spec_sections" in level_config
        assert "task_sections" in level_config
        assert "acceptance_criteria_depth" in level_config
        assert "semantics" in level_config
        semantics = level_config["semantics"]
        assert "target_implementor" in semantics
        assert "philosophy" in semantics
        assert "use_cases" in semantics
        assert "expectations" in semantics


def test_default_guidance(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    default = cfg.default_guidance()
    assert default in ["light", "standard", "deep"]
    assert default == "standard"


def test_guidance_defaults_applied(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    for level in ["light", "standard", "deep"]:
        level_config = cfg.guidance_for(level)
        defaults = level_config["defaults"]
        assert "current_understanding" in defaults
        assert "open_questions" in defaults
        assert isinstance(defaults["open_questions"], list)
        assert len(defaults["open_questions"]) > 0


def test_guidance_sections_by_depth(tmp_path: Path) -> None:
    root = _seed_base_config(tmp_path, include_optional=True)
    cfg = Config(root)
    light = cfg.guidance_for("light")
    standard = cfg.guidance_for("standard")
    deep = cfg.guidance_for("deep")
    light_required = len(light["spec_sections"]["required"])
    standard_required = len(standard["spec_sections"]["required"])
    deep_required = len(deep["spec_sections"]["required"])
    assert light_required <= standard_required <= deep_required
    assert light["acceptance_criteria_depth"] == "basic"
    assert standard["acceptance_criteria_depth"] == "standard"
    assert deep["acceptance_criteria_depth"] == "rigorous"
