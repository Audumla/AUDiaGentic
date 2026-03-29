from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
import yaml

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.lifecycle.fresh_install import apply_fresh_install
from tests.helpers import sandbox as sandbox_helper

SCHEMA_DIR = ROOT / "docs" / "schemas"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_fresh_install_creates_scaffold_and_manifest(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "fresh-install")
    try:
        result = apply_fresh_install(sandbox.repo)
        assert result["status"] == "success"
        assert (sandbox.repo / ".audiagentic" / "project.yaml").is_file()
        assert (sandbox.repo / ".audiagentic" / "components.yaml").is_file()
        assert (sandbox.repo / ".audiagentic" / "providers.yaml").is_file()
        assert (sandbox.repo / ".audiagentic" / "installed.json").is_file()

        project_cfg = _load_yaml(sandbox.repo / ".audiagentic" / "project.yaml")
        component_cfg = _load_yaml(sandbox.repo / ".audiagentic" / "components.yaml")
        provider_cfg = _load_yaml(sandbox.repo / ".audiagentic" / "providers.yaml")

        validator = Draft202012Validator(
            json.loads((SCHEMA_DIR / "project-config.schema.json").read_text(encoding="utf-8"))
        )
        assert not list(validator.iter_errors(project_cfg))
        validator = Draft202012Validator(
            json.loads((SCHEMA_DIR / "component-config.schema.json").read_text(encoding="utf-8"))
        )
        assert not list(validator.iter_errors(component_cfg))
        validator = Draft202012Validator(
            json.loads((SCHEMA_DIR / "provider-config.schema.json").read_text(encoding="utf-8"))
        )
        assert not list(validator.iter_errors(provider_cfg))

        manifest_payload = json.loads(
            (sandbox.repo / ".audiagentic" / "installed.json").read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(
            json.loads((SCHEMA_DIR / "installed-state.schema.json").read_text(encoding="utf-8"))
        )
        assert not list(validator.iter_errors(manifest_payload))
    finally:
        sandbox.cleanup()


def test_fresh_install_rejects_existing_state(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "fresh-install-existing")
    try:
        (sandbox.repo / ".audiagentic").mkdir(parents=True)
        (sandbox.repo / ".audiagentic" / "project.yaml").write_text("contract-version: v1", encoding="utf-8")
        try:
            apply_fresh_install(sandbox.repo)
        except AudiaGenticError as exc:
            assert exc.kind == "business-rule"
            assert (sandbox.repo / ".audiagentic" / "project.yaml").read_text(encoding="utf-8") == "contract-version: v1"
        else:
            raise AssertionError("expected business-rule error")
    finally:
        sandbox.cleanup()
