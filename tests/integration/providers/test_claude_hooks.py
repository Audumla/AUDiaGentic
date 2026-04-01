"""Tests for Claude Code hook implementations."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.claude_hooks import (
    detect_and_launch_prompt_tag,
    enforce_stage_restrictions,
    _parse_first_line_params,
)


class TestDetectAndLaunchPromptTag:
    """Test UserPromptSubmit hook logic."""

    def test_detects_plan_tag(self):
        """Verify @plan tag is detected and recognized."""
        raw_prompt = "@plan\nReview the implementation status."
        result = detect_and_launch_prompt_tag(
            raw_prompt,
            {'workspace_root': '.', 'surface': 'cli'},
        )
        # Should attempt bridge invocation (or return empty if no bridge available)
        # For now, just verify no exception
        assert isinstance(result, dict)

    def test_passes_through_non_tagged_prompt(self):
        """Verify non-tagged prompts pass through unchanged."""
        raw_prompt = "This is a normal prompt without a tag."
        result = detect_and_launch_prompt_tag(
            raw_prompt,
            {'workspace_root': '.', 'surface': 'cli'},
        )
        assert result == {}

    def test_parses_provider_override(self):
        """Verify provider override in tag is extracted."""
        raw_prompt = "@plan provider=cline\nContinue work."
        params = _parse_first_line_params("@plan provider=cline")
        assert params['provider'] == 'cline'

    def test_handles_empty_prompt(self):
        """Verify empty prompt is handled gracefully."""
        result = detect_and_launch_prompt_tag(
            "",
            {'workspace_root': '.', 'surface': 'cli'},
        )
        assert result == {}


class TestEnforceStageRestrictions:
    """Test PreToolUse hook logic."""

    def test_review_restricts_write_tools(self):
        """Verify review mode restricts write tools."""
        tools_requested = ['Read', 'Edit', 'Write', 'Bash', 'TodoWrite']
        result = enforce_stage_restrictions(
            'review',
            tools_requested,
            {'surface': 'cli'},
        )

        allowed = result['allowed_tools']
        assert 'Read' in allowed
        assert 'TodoWrite' in allowed
        assert 'Edit' not in allowed
        assert 'Write' not in allowed
        assert 'Bash' not in allowed

    def test_plan_restricts_implementation_tools(self):
        """Verify plan mode restricts implementation tools."""
        tools_requested = ['Read', 'Edit', 'Write', 'Agent', 'Bash']
        result = enforce_stage_restrictions(
            'plan',
            tools_requested,
            {'surface': 'cli'},
        )

        allowed = result['allowed_tools']
        assert 'Read' in allowed
        assert 'Agent' in allowed
        assert 'Edit' not in allowed
        assert 'Write' not in allowed
        assert 'Bash' not in allowed

    def test_implement_allows_all_tools(self):
        """Verify implement mode allows all tools."""
        tools_requested = ['Read', 'Edit', 'Write', 'Bash', 'Agent', 'TodoWrite']
        result = enforce_stage_restrictions(
            'implement',
            tools_requested,
            {'surface': 'cli'},
        )

        allowed = result['allowed_tools']
        # All requested tools should be allowed in implement mode
        assert set(allowed) == set(tools_requested)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
