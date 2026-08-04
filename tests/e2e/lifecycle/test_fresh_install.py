from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yaml
from jsonschema import Draft202012Validator
from tests.helpers import sandbox as sandbox_helper

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import read_schema
from audiagentic.foundation.lifecycle.fresh_install import apply_fresh_install


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_fresh_install_creates_scaffold_and_manifest(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "fresh-install")
    try:
        result = apply_fresh_install(sandbox.repo)
        assert result["status"] == "success"
        assert (sandbox.repo / ".audiagentic" / "config" / "project.yaml").is_file()
        assert not (sandbox.repo / ".audiagentic" / "config" / "runtime" / "providers.yaml").exists()
        assert not (
            sandbox.repo / ".audiagentic" / "config" / "execution" / "prompt-syntax.yaml"
        ).exists()
        assert (sandbox.repo / ".audiagentic" / "prompts" / "ag-review" / "default.md").exists()
        # Component markers are the new install record
        assert (sandbox.repo / ".audiagentic" / "components" / "project.yaml").is_file()
        assert not (sandbox.repo / ".audiagentic" / "components" / "providers.yaml").exists()
        assert not (sandbox.repo / ".audiagentic" / "components" / "agent-ledger.yaml").exists()
        assert not (sandbox.repo / ".audiagentic" / "components" / "memory.yaml").exists()
        assert not (sandbox.repo / ".audiagentic" / "components" / "agent-planning.yaml").exists()

        project_cfg = _load_yaml(sandbox.repo / ".audiagentic" / "config" / "project.yaml")
        validator = Draft202012Validator(read_schema("project-config"))
        assert not list(validator.iter_errors(project_cfg))

        # project marker has expected fields
        marker = _load_yaml(sandbox.repo / ".audiagentic" / "components" / "project.yaml")
        assert marker["component-id"] == "project"
        assert marker["enabled"] is True
        assert marker["installation-kind"] == "fresh"
    finally:
        sandbox.cleanup()


def test_fresh_install_rejects_existing_state(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "fresh-install-existing")
    try:
        (sandbox.repo / ".audiagentic").mkdir(parents=True)
        config_dir = sandbox.repo / ".audiagentic" / "config"
        config_dir.mkdir()
        (config_dir / "project.yaml").write_text("contract-version: v1", encoding="utf-8")
        try:
            apply_fresh_install(sandbox.repo)
        except AudiaGenticError as exc:
            assert exc.kind == "lifecycle"
            assert (
                sandbox.repo / ".audiagentic" / "config" / "project.yaml"
            ).read_text(encoding="utf-8") == "contract-version: v1"
        else:
            raise AssertionError("expected business-rule error")
    finally:
        sandbox.cleanup()
