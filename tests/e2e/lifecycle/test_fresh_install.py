from __future__ import annotations

from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from tests.helpers import sandbox as sandbox_helper

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.contracts.schema_registry import read_schema
from audiagentic.runtime.lifecycle.fresh_install import apply_fresh_install


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_fresh_install_creates_scaffold_and_manifest(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "fresh-install")
    try:
        result = apply_fresh_install(sandbox.repo)
        assert result["status"] == "success"
        assert (sandbox.repo / ".audiagentic" / "config" / "project.yaml").is_file()
        assert (sandbox.repo / ".audiagentic" / "config" / "runtime" / "providers.yaml").is_file()
        assert (
            sandbox.repo / ".audiagentic" / "config" / "execution" / "prompt-syntax.yaml"
        ).is_file()
        assert (sandbox.repo / ".audiagentic" / "prompts" / "ag-review" / "default.md").is_file()
        assert (sandbox.repo / "AGENTS.md").is_file()
        # Component markers are the new install record
        assert (sandbox.repo / ".audiagentic" / "components" / "core-lifecycle.yaml").is_file()
        assert any(
            path.startswith(".audiagentic/runtime/")
            for path in result["baseline-sync-report"]["excluded-paths"]
        )

        project_cfg = _load_yaml(sandbox.repo / ".audiagentic" / "config" / "project.yaml")
        provider_cfg = _load_yaml(
            sandbox.repo / ".audiagentic" / "config" / "runtime" / "providers.yaml"
        )

        validator = Draft202012Validator(read_schema("project-config"))
        assert not list(validator.iter_errors(project_cfg))
        validator = Draft202012Validator(read_schema("provider-config"))
        assert not list(validator.iter_errors(provider_cfg))

        # core-lifecycle marker has expected fields
        marker = _load_yaml(sandbox.repo / ".audiagentic" / "components" / "core-lifecycle.yaml")
        assert marker["component-id"] == "core-lifecycle"
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
            assert exc.kind == "business-rule"
            assert (
                sandbox.repo / ".audiagentic" / "config" / "project.yaml"
            ).read_text(encoding="utf-8") == "contract-version: v1"
        else:
            raise AssertionError("expected business-rule error")
    finally:
        sandbox.cleanup()
