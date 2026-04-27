"""Tests for config-driven planning counter isolation."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from src.audiagentic.planning.app.api import PlanningAPI


class TestConfigCounterIsolation:
    @pytest.fixture
    def test_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = root / ".audiagentic" / "planning" / "config"
            config.mkdir(parents=True)

            src_config = Path(__file__).parent.parent / ".audiagentic" / "planning" / "config"
            for yaml_file in ("planning.yaml", "profiles.yaml", "workflows.yaml", "automations.yaml"):
                shutil.copy2(src_config / yaml_file, config / yaml_file)

            template_src = src_config / "templates"
            template_dst = config / "templates"
            if template_src.exists():
                shutil.copytree(template_src, template_dst)

            yield root

    def test_api_creates_items_with_configured_counter(self, test_project: Path) -> None:
        api = PlanningAPI(test_project)

        item1 = api.create_with_content(
            "standard", "Standard 1", "First standard", "# Test Content"
        )
        item2 = api.create_with_content(
            "standard", "Standard 2", "Second standard", "# Test Content"
        )

        assert item1.data["id"] == "standard-1"
        assert item2.data["id"] == "standard-2"
        assert (test_project / ".audiagentic" / "planning" / "meta" / "standards.json").is_file()

    def test_separate_roots_have_independent_configured_counters(
        self, tmp_path: Path, test_project: Path
    ) -> None:
        other_root = tmp_path / "other"
        shutil.copytree(test_project / ".audiagentic", other_root / ".audiagentic")

        first = PlanningAPI(test_project).create_with_content("standard", "Root one", "First root", "# Test")
        second = PlanningAPI(other_root).create_with_content("standard", "Root two", "Second root", "# Test")

        assert first.data["id"] == "standard-1"
        assert second.data["id"] == "standard-1"
