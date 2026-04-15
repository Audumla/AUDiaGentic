"""Test ID normalization and lookup with various formats.

Verifies that PlanningAPI.lookup() handles different ID formats correctly:
- request-0020 (standard padded)
- request-20 (unpadded)
- request-020 (partial padding)
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.audiagentic.planning.app.api import PlanningAPI


@pytest.fixture
def api():
    return PlanningAPI(ROOT)


class TestRequestLookup:
    """Test request lookup with various ID formats."""

    def test_lookup_standard_padded(self, api):
        """Test lookup with standard padded ID (request-020)."""
        item = api.lookup("request-020")
        assert item.kind == "request"
        assert item.data["id"] == "request-020"

    def test_lookup_unpadded(self, api):
        """Test lookup with unpadded ID (request-20)."""
        item = api.lookup("request-20")
        assert item.kind == "request"
        assert item.data["id"] == "request-020"

    def test_lookup_partial_padding(self, api):
        """Test lookup with partial padding (request-020)."""
        item = api.lookup("request-020")
        assert item.kind == "request"
        assert item.data["id"] == "request-020"

    def test_lookup_single_digit_unpadded(self, api):
        """Test lookup with single digit unpadded (request-1)."""
        item = api.lookup("request-1")
        assert item.kind == "request"
        assert item.data["id"] == "request-001"

    def test_lookup_single_digit_padded(self, api):
        """Test lookup with single digit padded (request-001)."""
        item = api.lookup("request-001")
        assert item.kind == "request"
        assert item.data["id"] == "request-001"

    def test_lookup_nonexistent_shows_closest(self, api):
        """Test that nonexistent ID shows closest match."""
        with pytest.raises(ValueError) as exc_info:
            api.lookup("request-999")

        error_msg = str(exc_info.value)
        assert "request-999 not found" in error_msg
        assert "Closest:" in error_msg
        assert "request-020" in error_msg  # Should suggest highest existing


class TestTaskLookup:
    """Test task lookup with various ID formats."""

    def test_lookup_task_standard_padded(self, api):
        """Test task lookup with standard padded ID (task-0001)."""
        item = api.lookup("task-0001")
        assert item.kind == "task"
        assert item.data["id"] == "task-0001"

    def test_lookup_task_unpadded(self, api):
        """Test task lookup with unpadded ID (task-1)."""
        item = api.lookup("task-1")
        assert item.kind == "task"
        assert item.data["id"] == "task-0001"

    def test_lookup_task_partial_padding(self, api):
        """Test task lookup with partial padding (task-001)."""
        item = api.lookup("task-001")
        assert item.kind == "task"
        assert item.data["id"] == "task-0001"


class TestSpecLookup:
    """Test spec lookup with various ID formats."""

    def test_lookup_spec_standard_padded(self, api):
        """Test spec lookup with standard padded ID (spec-001)."""
        item = api.lookup("spec-001")
        assert item.kind == "spec"
        assert item.data["id"] == "spec-001"

    def test_lookup_spec_unpadded(self, api):
        """Test spec lookup with unpadded ID (spec-1)."""
        item = api.lookup("spec-1")
        assert item.kind == "spec"
        assert item.data["id"] == "spec-001"


class TestPlanLookup:
    """Test plan lookup with various ID formats."""

    def test_lookup_plan_standard_padded(self, api):
        """Test plan lookup with standard padded ID (plan-001)."""
        item = api.lookup("plan-001")
        assert item.kind == "plan"
        assert item.data["id"] == "plan-001"

    def test_lookup_plan_unpadded(self, api):
        """Test plan lookup with unpadded ID (plan-1)."""
        item = api.lookup("plan-1")
        assert item.kind == "plan"
        assert item.data["id"] == "plan-001"


class TestWPlookup:
    """Test work package lookup with various ID formats."""

    def test_lookup_wp_standard_padded(self, api):
        """Test WP lookup with standard padded ID (wp-001)."""
        item = api.lookup("wp-001")
        assert item.kind == "wp"
        assert item.data["id"] == "wp-001"

    def test_lookup_wp_unpadded(self, api):
        """Test WP lookup with unpadded ID (wp-1)."""
        item = api.lookup("wp-1")
        assert item.kind == "wp"
        assert item.data["id"] == "wp-001"


class TestErrorMessages:
    """Test that error messages are helpful."""

    def test_error_shows_available_items(self, api):
        """Test error message shows available items."""
        with pytest.raises(ValueError) as exc_info:
            api.lookup("request-999")

        error_msg = str(exc_info.value)
        assert "Available" in error_msg
        assert "tm_list" in error_msg

    def test_error_shows_normalization_attempt(self, api):
        """Test error message shows normalization was attempted."""
        with pytest.raises(ValueError) as exc_info:
            api.lookup("request-99")

        error_msg = str(exc_info.value)
        assert "tried request-099" in error_msg
