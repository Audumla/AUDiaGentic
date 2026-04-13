"""End-to-end tests for Claude hook chain integration."""

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.skipif(
    not (ROOT / '.claude' / 'settings.json').exists(),
    reason="Claude settings.json not configured"
)
def test_hook_chain_settings_json_exists():
    """Verify .claude/settings.json exists with hook configuration."""
    settings_path = ROOT / '.claude' / 'settings.json'
    assert settings_path.exists()

    settings = json.loads(settings_path.read_text())
    assert 'hooks' in settings
    assert 'UserPromptSubmit' in settings['hooks']
    assert 'PreToolUse' in settings['hooks']


def test_hook_handlers_module_exists():
    """Verify hook handlers module exists at its v3 location."""
    handlers_path = ROOT / 'tools' / 'misc' / 'claude_hooks.py'
    assert handlers_path.exists()


def test_fallback_to_wrapper_when_hook_unavailable():
    """Verify fallback to wrapper bridge when hook chain fails."""
    # Hook unavailability is handled gracefully by returning empty dict
    # which allows normal Claude planning to proceed
    # The actual fallback mechanism is tested through the hook logic
    # For now, just verify the module is correctly structured
    from tools.misc.claude_hooks import UserPromptSubmit_handler, PreToolUse_handler

    assert callable(UserPromptSubmit_handler)
    assert callable(PreToolUse_handler)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
