"""Keep planning documentation and tool guidance aligned with workflows.yaml."""
from __future__ import annotations

import re
from pathlib import Path

from audiagentic.foundation.io import load_yaml_file

ROOT = Path(__file__).resolve().parents[3]


def test_documented_planning_states_match_runtime_workflow() -> None:
    workflow = load_yaml_file(ROOT / "src/audiagentic/components/planning/workflows.yaml")
    planning_readme = (ROOT / "src/audiagentic/components/planning/README.md").read_text(
        encoding="utf-8"
    )
    planning_config = (ROOT / "src/audiagentic/config/components/planning.yaml").read_text(
        encoding="utf-8"
    )
    creating_plans = (ROOT / "docs/planning/CREATING_PLANS.md").read_text(encoding="utf-8")
    readme_flat = re.sub(r"\s+", " ", planning_readme)
    creating_flat = re.sub(r"\s+", " ", creating_plans)
    config_flat = re.sub(r"\s+", " ", planning_config)
    surfaces = {
        "README": readme_flat,
        "CREATING_PLANS": creating_flat,
        "planning.yaml": config_flat,
    }
    assert "acceptance_criteria:" in planning_config
    assert "completed items cannot receive or" in planning_readme.lower()
    assert "completed items cannot receive or" in creating_plans.lower()
    assert "all linked reviews are closed" in config_flat.lower()
    assert "completion requires non-empty `validation` and `acceptance criteria`" in creating_flat.lower()
    assert "completion requires non-empty validation and acceptance criteria" in config_flat.lower()
    for kind in ("item", "review"):
        definition = workflow["kinds"][kind]["workflows"]["standard"]
        for surface_name, surface in surfaces.items():
            assert definition["initial"] in surface, f"{surface_name} omits {kind} initial state"
            for state in definition["values"]:
                assert state in surface, f"{surface_name} omits {kind} state {state}"
            for _state, placement in definition["placement"].items():
                assert placement in surface, f"{surface_name} omits {kind} placement {placement}"
        for source, targets in definition["transitions"].items():
            assert source in definition["values"]
            assert set(targets).issubset(set(definition["values"]))
            transition = f"`{source}` → " + ", ".join(f"`{target}`" for target in targets)
            ascii_transition = f"{source} -> " + ", ".join(targets)
            assert transition in readme_flat
            assert transition in creating_flat
            assert ascii_transition in config_flat
    assert "Item initial state: `pending`" in creating_flat
    assert "Review initial state: `created`" in creating_flat
    assert "pending/in_progress are placed in active/" in config_flat
    assert "created/considered are placed in active/" in config_flat
    for source, targets in workflow["kinds"]["review"]["workflows"]["standard"]["transitions"].items():
        ascii_transition = f"{source} -> " + ", ".join(targets)
        assert ascii_transition in config_flat
