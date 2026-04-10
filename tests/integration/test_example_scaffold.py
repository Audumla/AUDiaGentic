from __future__ import annotations

import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.schema_registry import read_schema
import tools.misc.seed_example_project as seed_example_project


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _validate(schema_name: str, payload: dict) -> None:
    validator = Draft202012Validator(read_schema(schema_name))
    errors = list(validator.iter_errors(payload))
    assert not errors


def test_scaffold_seed_creates_layout(tmp_path: Path) -> None:
    target = tmp_path / "project"
    seed_example_project.seed_example_project(target)
    assert (target / "docs" / "specifications").is_dir()
    assert (target / "docs" / "implementation").is_dir()
    assert (target / "docs" / "releases").is_dir()
    assert (target / "docs" / "decisions").is_dir()
    assert (target / ".audiagentic" / "runtime").is_dir()
    assert (target / ".audiagentic" / "providers.yaml").is_file()
    assert (target / ".audiagentic" / "prompt-syntax.yaml").is_file()
    assert (target / ".audiagentic" / "providers.yaml").is_file()
    assert (target / ".audiagentic" / "prompt-syntax.yaml").is_file()
    assert (target / ".audiagentic" / "prompts" / "ag-review" / "default.md").is_file()
    assert (target / "AGENTS.md").is_file()
    assert (target / ".github" / "workflows" / "release-please.audiagentic.yml").is_file()


def test_scaffold_configs_validate(tmp_path: Path) -> None:
    target = tmp_path / "project"
    seed_example_project.seed_example_project(target)
    _validate("provider-config", _load_yaml(target / ".audiagentic" / "providers.yaml"))
    _validate("prompt-syntax", _load_yaml(target / ".audiagentic" / "prompt-syntax.yaml"))


def test_seed_refuses_non_empty_target(tmp_path: Path) -> None:
    target = tmp_path / "project"
    target.mkdir()
    (target / "existing.txt").write_text("data", encoding="utf-8")
    try:
        seed_example_project.seed_example_project(target)
    except FileExistsError:
        assert (target / "existing.txt").read_text(encoding="utf-8") == "data"
    else:
        raise AssertionError("expected FileExistsError")


def test_seed_is_idempotent_with_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "project"
    seed_example_project.seed_example_project(target)
    first = (target / ".audiagentic" / "providers.yaml").read_text(encoding="utf-8")
    seed_example_project.seed_example_project(target, overwrite=True)
    second = (target / ".audiagentic" / "providers.yaml").read_text(encoding="utf-8")
    assert first == second
