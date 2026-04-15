"""Tests for PlanningAPI test_mode isolation.

Verifies that test_mode uses separate counters from real system,
preventing ID collisions during parallel testing.
"""

import json
import shutil
import tempfile
from pathlib import Path

import pytest
from src.audiagentic.planning.app.api import PlanningAPI
from src.audiagentic.planning.app.id_gen import _counters_path, _load_counters, next_id


class TestTestModeIsolation:
    """Test that test_mode properly isolates counters from real system."""

    @pytest.fixture
    def test_project(self):
        """Create a temporary project with planning structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create real planning structure
            real_config = root / ".audiagentic" / "planning" / "config"
            real_config.mkdir(parents=True)

            # Copy minimal config files
            src_config = Path(__file__).parent.parent / ".audiagentic" / "planning" / "config"
            for yaml_file in [
                "planning.yaml",
                "profiles.yaml",
                "workflows.yaml",
                "automations.yaml",
            ]:
                if (src_config / yaml_file).exists():
                    shutil.copy2(src_config / yaml_file, real_config / yaml_file)

            # Create profile-packs directory
            profile_packs = real_config / "profile-packs"
            profile_packs.mkdir(exist_ok=True)
            if (src_config / "profile-packs").exists():
                for f in (src_config / "profile-packs").iterdir():
                    if f.is_file():
                        shutil.copy2(f, profile_packs / f.name)

            # Create docs structure
            docs_tasks = root / "docs" / "planning" / "tasks" / "core"
            docs_tasks.mkdir(parents=True)

            # Create test planning structure (with .audiagentic subdirectory)
            test_config = root / "test" / ".audiagentic" / "planning" / "config"
            test_config.mkdir(parents=True)
            for yaml_file in [
                "planning.yaml",
                "profiles.yaml",
                "workflows.yaml",
                "automations.yaml",
            ]:
                if (real_config / yaml_file).exists():
                    shutil.copy2(real_config / yaml_file, test_config / yaml_file)

            test_profile_packs = test_config / "profile-packs"
            test_profile_packs.mkdir(exist_ok=True)
            if (real_config / "profile-packs").exists():
                for f in (real_config / "profile-packs").iterdir():
                    if f.is_file():
                        shutil.copy2(f, test_profile_packs / f.name)

            # Create test docs structure
            test_docs_tasks = root / "test" / "planning" / "tasks" / "core"
            test_docs_tasks.mkdir(parents=True)

            yield root

    def test_counters_separate(self, test_project):
        """Test that test and real counters are in separate files."""
        real_counters_path = _counters_path(test_project, test_mode=False)
        test_counters_path = _counters_path(test_project, test_mode=True)

        assert real_counters_path != test_counters_path
        assert "test" not in str(real_counters_path)
        assert "test" in str(test_counters_path)

    def test_next_id_isolation(self, test_project):
        """Test that next_id returns independent IDs for test and real modes."""
        real_id1 = next_id(test_project, "task", test_mode=False)
        test_id1 = next_id(test_project, "task", test_mode=True)

        # Both should be valid task IDs starting from 1
        assert real_id1.startswith("task-")
        assert test_id1.startswith("task-")

        # Generate second IDs - should increment independently
        real_id2 = next_id(test_project, "task", test_mode=False)
        test_id2 = next_id(test_project, "task", test_mode=True)

        # Each mode should have incremented
        assert real_id1 != real_id2
        assert test_id1 != test_id2

        # Extract numbers to verify independent sequences
        real_num1 = int(real_id1.split("-")[1])
        real_num2 = int(real_id2.split("-")[1])
        test_num1 = int(test_id1.split("-")[1])
        test_num2 = int(test_id2.split("-")[1])

        # Both should start from 1 and increment by 1
        assert real_num1 == 1
        assert test_num1 == 1
        assert real_num2 == 2
        assert test_num2 == 2

    def test_counter_increment_independent(self, test_project):
        """Test that incrementing one counter doesn't affect the other."""
        # Get initial IDs
        real_id1 = next_id(test_project, "task", test_mode=False)
        test_id1 = next_id(test_project, "task", test_mode=True)

        # Increment test counter
        test_id2 = next_id(test_project, "task", test_mode=True)

        # Real counter should be unchanged
        real_id2 = next_id(test_project, "task", test_mode=False)

        # Test counter incremented
        assert test_id1 != test_id2

        # Real counter also incremented (but independently)
        assert real_id1 != real_id2

        # Extract numbers and verify they're different sequences
        real_num1 = int(real_id1.split("-")[1])
        real_num2 = int(real_id2.split("-")[1])
        test_num1 = int(test_id1.split("-")[1])
        test_num2 = int(test_id2.split("-")[1])

        # Each sequence should increment by 1
        assert real_num2 == real_num1 + 1
        assert test_num2 == test_num1 + 1

    def test_api_test_mode_creates_items(self, test_project):
        """Test that PlanningAPI in test_mode can create items."""
        api = PlanningAPI(test_project, test_mode=True)

        task = api.create_with_content(
            "task", "Test Task", "Test summary", "# Test Content", domain="core"
        )

        assert task is not None
        assert task.kind == "task"
        assert task.data["id"].startswith("task-")
        assert task.data["label"] == "Test Task"
        assert task.data["summary"] == "Test summary"

    def test_api_real_mode_creates_items(self, test_project):
        """Test that PlanningAPI in real mode can create items."""
        api = PlanningAPI(test_project, test_mode=False)

        task = api.create_with_content(
            "task", "Real Task", "Real summary", "# Real Content", domain="core"
        )

        assert task is not None
        assert task.kind == "task"
        assert task.data["id"].startswith("task-")
        assert task.data["label"] == "Real Task"
        assert task.data["summary"] == "Real summary"

    def test_test_and_real_no_collision(self, test_project):
        """Test that test and real modes don't collide on IDs."""
        # Create items in both modes
        test_api = PlanningAPI(test_project, test_mode=True)
        real_api = PlanningAPI(test_project, test_mode=False)

        test_task1 = test_api.create_with_content(
            "task", "Test Task 1", "Test", "# Test", domain="core"
        )
        real_task1 = real_api.create_with_content(
            "task", "Real Task 1", "Real", "# Real", domain="core"
        )

        # First IDs may be same (both start from 1)
        # Create second items to verify independent incrementing
        test_task2 = test_api.create_with_content(
            "task", "Test Task 2", "Test", "# Test", domain="core"
        )
        real_task2 = real_api.create_with_content(
            "task", "Real Task 2", "Real", "# Real", domain="core"
        )

        # Extract ID numbers
        test_num1 = int(test_task1.data["id"].split("-")[1])
        test_num2 = int(test_task2.data["id"].split("-")[1])
        real_num1 = int(real_task1.data["id"].split("-")[1])
        real_num2 = int(real_task2.data["id"].split("-")[1])

        # Both should start from 1
        assert test_num1 == 1
        assert real_num1 == 1

        # Both should increment independently
        assert test_num2 == 2
        assert real_num2 == 2

        # Clean up
        for task in [test_task1, test_task2, real_task1, real_task2]:
            task.path.unlink(missing_ok=True)

    def test_multiple_kinds_isolated(self, test_project):
        """Test that multiple kinds (task, spec, plan, etc.) are all isolated."""
        kinds = ["task", "spec", "plan", "wp", "request"]

        for kind in kinds:
            real_id = next_id(test_project, kind, test_mode=False)
            test_id = next_id(test_project, kind, test_mode=True)

            # Both should have correct prefix
            assert real_id.startswith(f"{kind}-")
            assert test_id.startswith(f"{kind}-")

            # Test ID should start from low number (1-999)
            test_num = int(test_id.split("-")[1])
            assert test_num < 1000, f"Test {kind} ID should be low, got {test_id}"

    def test_counter_file_format(self, test_project):
        """Test that counter files have correct JSON format."""
        # Generate some IDs
        next_id(test_project, "task", test_mode=True)
        next_id(test_project, "spec", test_mode=True)

        # Load and verify format
        counters = _load_counters(test_project, test_mode=True)

        assert isinstance(counters, dict)
        assert "task" in counters
        assert "spec" in counters
        assert counters["task"] >= 1
        assert counters["spec"] >= 1

        # Verify file exists and is valid JSON
        counters_path = _counters_path(test_project, test_mode=True)
        assert counters_path.exists()

        with open(counters_path) as f:
            data = json.load(f)

        assert "version" in data
        assert "counters" in data
        assert isinstance(data["counters"], dict)


class TestParallelSafety:
    """Test that parallel execution is safe with test_mode."""

    @pytest.fixture
    def test_project(self):
        """Create a temporary project with planning structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create minimal structure
            real_config = root / ".audiagentic" / "planning" / "config"
            real_config.mkdir(parents=True)

            src_config = Path(__file__).parent.parent / ".audiagentic" / "planning" / "config"
            for yaml_file in [
                "planning.yaml",
                "profiles.yaml",
                "workflows.yaml",
                "automations.yaml",
            ]:
                if (src_config / yaml_file).exists():
                    shutil.copy2(src_config / yaml_file, real_config / yaml_file)

            profile_packs = real_config / "profile-packs"
            profile_packs.mkdir(exist_ok=True)

            docs_tasks = root / "docs" / "planning" / "tasks" / "core"
            docs_tasks.mkdir(parents=True)

            test_config = root / "test" / ".audiagentic" / "planning" / "config"
            test_config.mkdir(parents=True)
            for yaml_file in [
                "planning.yaml",
                "profiles.yaml",
                "workflows.yaml",
                "automations.yaml",
            ]:
                if (real_config / yaml_file).exists():
                    shutil.copy2(real_config / yaml_file, test_config / yaml_file)

            test_profile_packs = test_config / "profile-packs"
            test_profile_packs.mkdir(exist_ok=True)
            if (real_config / "profile-packs").exists():
                for f in (real_config / "profile-packs").iterdir():
                    if f.is_file():
                        shutil.copy2(f, test_profile_packs / f.name)

            test_docs_tasks = root / "test" / "planning" / "tasks" / "core"
            test_docs_tasks.mkdir(parents=True)

            yield root

    def test_concurrent_id_generation(self, test_project):
        """Test that concurrent ID generation doesn't cause collisions."""
        import threading
        import time

        test_ids = []
        real_ids = []
        errors = []

        def generate_test_ids(count):
            try:
                for _ in range(count):
                    id_ = next_id(test_project, "task", test_mode=True)
                    test_ids.append(id_)
                    time.sleep(0.001)  # Small delay to increase chance of race
            except Exception as e:
                errors.append(e)

        def generate_real_ids(count):
            try:
                for _ in range(count):
                    id_ = next_id(test_project, "task", test_mode=False)
                    real_ids.append(id_)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        # Run both threads concurrently
        t1 = threading.Thread(target=generate_test_ids, args=(10,))
        t2 = threading.Thread(target=generate_real_ids, args=(10,))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # No errors
        assert len(errors) == 0, f"Errors occurred: {errors}"

        # All IDs unique within each set
        assert len(test_ids) == len(set(test_ids)), "Test IDs have duplicates"
        assert len(real_ids) == len(set(real_ids)), "Real IDs have duplicates"

        # Both sequences should be contiguous starting from 1
        test_nums = sorted(int(id_.split("-")[1]) for id_ in test_ids)
        real_nums = sorted(int(id_.split("-")[1]) for id_ in real_ids)

        assert test_nums == list(range(1, 11)), f"Test IDs not contiguous: {test_nums}"
        assert real_nums == list(range(1, 11)), f"Real IDs not contiguous: {real_nums}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
