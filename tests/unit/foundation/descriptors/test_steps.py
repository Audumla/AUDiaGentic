"""Tests for foundation/descriptors/steps.py"""
from __future__ import annotations

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.descriptors.steps import build_step_from_spec
from audiagentic.foundation.workflow.invocation.steps import (
    CallableStep,
    ConditionalStep,
    ConfirmStep,
    SequenceStep,
    ShellStep,
)


class TestBuildStepFromSpec:
    """Test workflow step construction from declarative specs."""

    def test_shell_step_basic(self) -> None:
        """Build a basic shell step."""
        spec = {"type": "shell", "id": "test", "command": ["echo", "hello"]}
        step = build_step_from_spec(spec)
        assert isinstance(step, ShellStep)
        assert step.id == "test"
        assert step.command == ("echo", "hello")

    def test_shell_step_with_timeout(self) -> None:
        """Build shell step with custom timeout."""
        spec = {"type": "shell", "id": "test", "command": ["sleep", "1"], "timeout": 60}
        step = build_step_from_spec(spec)
        assert step.timeout == 60

    def test_shell_step_with_platform(self) -> None:
        """Build shell step with platform overrides."""
        spec = {
            "type": "shell",
            "id": "test",
            "command": ["echo", "hello"],
            "platform": {"win": ["cmd", "/c", "echo hello"], "darwin": None, "linux": None},
        }
        step = build_step_from_spec(spec)
        assert step.platform is not None
        assert step.platform.win == ("cmd", "/c", "echo hello")

    def test_shell_step_missing_command_raises(self) -> None:
        """Shell step without command raises VAL-DESC-002."""
        spec = {"type": "shell", "id": "test"}
        with pytest.raises(AudiaGenticError, match="VAL-DESC-002"):
            build_step_from_spec(spec)

    def test_callable_step(self) -> None:
        """Build a callable step from ref."""
        spec = {
            "type": "callable",
            "id": "test_fn",
            "fn": "audiagentic.foundation.mcp.json_format:read_mcp_json",
        }
        step = build_step_from_spec(spec)
        assert isinstance(step, CallableStep)
        assert step.id == "test_fn"
        assert callable(step.fn)

    def test_callable_step_missing_fn_raises(self) -> None:
        """Callable step without fn raises VAL-DESC-002."""
        spec = {"type": "callable", "id": "test"}
        with pytest.raises(AudiaGenticError, match="VAL-DESC-002"):
            build_step_from_spec(spec)

    def test_sequence_step(self) -> None:
        """Build a sequence step with child steps."""
        spec = {
            "type": "sequence",
            "id": "seq",
            "steps": [
                {"type": "shell", "id": "s1", "command": ["echo", "one"]},
                {"type": "shell", "id": "s2", "command": ["echo", "two"]},
            ],
        }
        step = build_step_from_spec(spec)
        assert isinstance(step, SequenceStep)
        assert len(step.steps) == 2
        assert step.steps[0].id == "s1"
        assert step.steps[1].id == "s2"

    def test_confirm_step(self) -> None:
        """Build a confirm step."""
        spec = {"type": "confirm", "id": "ask", "prompt": "Continue?"}
        step = build_step_from_spec(spec)
        assert isinstance(step, ConfirmStep)
        assert step.prompt == "Continue?"

    def test_confirm_step_missing_prompt_raises(self) -> None:
        """Confirm step without prompt raises VAL-DESC-002."""
        spec = {"type": "confirm", "id": "ask"}
        with pytest.raises(AudiaGenticError, match="VAL-DESC-002"):
            build_step_from_spec(spec)

    def test_conditional_step(self) -> None:
        """Build a conditional step."""
        spec = {
            "type": "conditional",
            "id": "check",
            "condition_key": "has_cli",
            "when_true": {"type": "shell", "id": "yes", "command": ["echo", "yes"]},
            "when_false": {"type": "shell", "id": "no", "command": ["echo", "no"]},
        }
        step = build_step_from_spec(spec)
        assert isinstance(step, ConditionalStep)
        assert step.condition_key == "has_cli"

    def test_unknown_type_raises(self) -> None:
        """Unknown step type raises VAL-DESC-002."""
        spec = {"type": "unknown", "id": "test"}
        with pytest.raises(AudiaGenticError, match="VAL-DESC-002"):
            build_step_from_spec(spec)

    def test_missing_type_raises(self) -> None:
        """Missing type raises VAL-DESC-002."""
        spec = {"id": "test"}
        with pytest.raises(AudiaGenticError, match="VAL-DESC-002"):
            build_step_from_spec(spec)
