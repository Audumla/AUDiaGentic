from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.runtime.lifecycle.manifest import build_manifest, write_manifest
from audiagentic.runtime.lifecycle.uninstall import apply_uninstall
from tests.helpers import sandbox as sandbox_helper
from tools.misc.seed_example_project import seed_example_project


def _write_manifest(root: Path) -> None:
    payload = build_manifest(
        installation_kind="fresh",
        current_version="0.1.0",
        previous_version=None,
        components={"core-lifecycle": "installed"},
        providers={"local-openai": "configured"},
        last_lifecycle_action="fresh-install",
    )
    write_manifest(root, payload)


def test_uninstall_default_preserves_configs(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "uninstall-default")
    try:
        seed_example_project(sandbox.repo, overwrite=True)
        _write_manifest(sandbox.repo)
        runtime_dir = sandbox.repo / ".audiagentic" / "runtime"
        assert runtime_dir.exists()

        result = apply_uninstall(sandbox.repo)
        assert result["status"] == "success"
        assert not runtime_dir.exists()
        assert (sandbox.repo / ".audiagentic" / "project.yaml").is_file()
        assert (sandbox.repo / ".audiagentic" / "components.yaml").is_file()
        assert (sandbox.repo / ".audiagentic" / "providers.yaml").is_file()
        assert not (sandbox.repo / ".audiagentic" / "installed.json").exists()
    finally:
        sandbox.cleanup()


def test_uninstall_remove_configs(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "uninstall-remove")
    try:
        seed_example_project(sandbox.repo, overwrite=True)
        _write_manifest(sandbox.repo)
        result = apply_uninstall(sandbox.repo, remove_configs=True)
        assert result["status"] == "success"
        assert not (sandbox.repo / ".audiagentic" / "project.yaml").exists()
        assert not (sandbox.repo / ".audiagentic" / "components.yaml").exists()
        assert not (sandbox.repo / ".audiagentic" / "providers.yaml").exists()
    finally:
        sandbox.cleanup()


def test_uninstall_rejects_non_audiagentic(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "uninstall-invalid")
    try:
        try:
            apply_uninstall(sandbox.repo)
        except AudiaGenticError as exc:
            assert exc.kind == "business-rule"
        else:
            raise AssertionError("expected business-rule error")
    finally:
        sandbox.cleanup()
