"""Tests for MCP helper root configurability."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _seed_test_project(tmp_path: Path) -> Path:
    """Seed a test project with minimal planning config."""
    config_dir = tmp_path / ".audiagentic" / "planning" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    src_config = ROOT / ".audiagentic" / "planning" / "config"
    for name in (
        "planning.yaml",
        "profiles.yaml",
        "workflows.yaml",
        "automations.yaml",
    ):
        shutil.copy(src_config / name, config_dir / name)

    for rel in ("ids", "indexes", "events", "claims", "meta"):
        (tmp_path / ".audiagentic" / "planning" / rel).mkdir(parents=True, exist_ok=True)

    docs_dir = tmp_path / "docs" / "planning"
    for d in (
        "requests",
        "specifications",
        "plans",
        "tasks/core",
        "work-packages/core",
        "standards",
    ):
        (docs_dir / d).mkdir(parents=True, exist_ok=True)

    (docs_dir / "specifications" / "spec-0001.md").write_text(
        "---\nid: spec-0001\nlabel: Default spec\nstate: draft\n---\n"
    )

    return tmp_path


class TestMCPHelperRootConfigurability:
    """Tests for MCP helper root directory configurability."""

    def test_set_root_and_create_task(self, tmp_path: Path) -> None:
        """set_root allows creating items in isolated directory."""
        import tools.planning.tm_helper as tm

        _seed_test_project(tmp_path)

        original_root = tm._get_root()
        try:
            tm.set_root(tmp_path)

            task = tm.new_task(label="Test", summary="Test", spec="spec-0001")

            isolated_file = tmp_path / "docs" / "planning" / "tasks" / "core" / f"{task['id']}.md"
            assert isolated_file.exists()

        finally:
            tm.reset_root()
            assert tm._get_root() == original_root

    def test_explicit_root_parameter(self, tmp_path: Path) -> None:
        """Helper functions accept explicit root parameter."""
        import tools.planning.tm_helper as tm

        _seed_test_project(tmp_path)

        task = tm.new_task(label="Test", summary="Test", spec="spec-0001", root=tmp_path)

        isolated_file = tmp_path / "docs" / "planning" / "tasks" / "core" / f"{task['id']}.md"
        assert isolated_file.exists()

    def test_validate_with_custom_root(self, tmp_path: Path) -> None:
        """validate works with custom root."""
        import tools.planning.tm_helper as tm

        _seed_test_project(tmp_path)

        errors = tm.validate(root=tmp_path)
        assert isinstance(errors, list)

    def test_list_kind_with_custom_root(self, tmp_path: Path) -> None:
        """list_kind works with custom root."""
        import tools.planning.tm_helper as tm

        _seed_test_project(tmp_path)

        items = tm.list_kind(root=tmp_path)
        assert any(item["id"] == "spec-0001" for item in items)
