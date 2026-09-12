"""Keep planning documentation and tool guidance aligned with workflows.yaml."""
from __future__ import annotations

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
    assert "acceptance_criteria:" in planning_config
    assert "completed items cannot receive or" in planning_readme.lower()
    for kind in ("item", "review"):
        definition = workflow["kinds"][kind]["workflows"]["standard"]
        assert f"start in `{definition['initial']}`" in planning_readme
        for state in definition["values"]:
            assert f"{chr(96)}{state}{chr(96)}" in planning_readme
        for _state, placement in definition["placement"].items():
            assert f"{chr(96)}{placement}/{chr(96)}" in planning_readme
        for source, targets in definition["transitions"].items():
            assert source in definition["values"]
            assert set(targets).issubset(set(definition["values"]))
