from __future__ import annotations

from pathlib import Path

import yaml
from tests.helpers import sandbox as sandbox_helper
from tools.misc.seed_example_project import seed_example_project

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime.lifecycle.uninstall import apply_uninstall


def _write_core_lifecycle_marker(root: Path) -> None:
    marker_dir = root / ".audiagentic" / "components"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = {
        "component-id": "core-lifecycle",
        "enabled": True,
        "installation-kind": "fresh",
        "installed-at": "2026-05-15T10:00:00Z",
        "last-lifecycle-action": "fresh-install",
        "version": "0.1.0",
    }
    (marker_dir / "core-lifecycle.yaml").write_text(
        yaml.dump(marker, default_flow_style=False, sort_keys=True), encoding="utf-8"
    )


def test_uninstall_default_preserves_configs(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "uninstall-default")
    try:
        seed_example_project(sandbox.repo, overwrite=True)
        _write_core_lifecycle_marker(sandbox.repo)
        runtime_dir = sandbox.repo / ".audiagentic" / "runtime"
        assert runtime_dir.exists()

        result = apply_uninstall(sandbox.repo)
        assert result["status"] == "success"
        assert not runtime_dir.exists()
        assert (sandbox.repo / ".audiagentic" / "config" / "project.yaml").is_file()
        assert (sandbox.repo / ".audiagentic" / "config" / "runtime" / "providers.yaml").is_file()
        # core-lifecycle marker is removed by uninstall_component (it's a create-if-missing file)
    finally:
        sandbox.cleanup()


def test_uninstall_remove_configs(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "uninstall-remove")
    try:
        seed_example_project(sandbox.repo, overwrite=True)
        _write_core_lifecycle_marker(sandbox.repo)
        result = apply_uninstall(sandbox.repo, remove_configs=True)
        assert result["status"] == "success"
        assert not (sandbox.repo / ".audiagentic" / "config" / "project.yaml").exists()
        assert not (sandbox.repo / ".audiagentic" / "config" / "runtime" / "providers.yaml").exists()
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
