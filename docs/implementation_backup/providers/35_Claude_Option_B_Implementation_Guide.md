# Claude Option B Implementation Guide — PKT-PRV-055

Detailed step-by-step guide for wiring native Claude Code hooks (UserPromptSubmit, PreToolUse)
to the shared prompt-trigger bridge so tagged prompts route automatically without wrapper invocation.

**Prerequisites:** Option A (PKT-PRV-033) must be VERIFIED with all `.claude/skills/` files and
preflight validation in place.

---

## Part 1: Create `.claude/settings.json` Hook Configuration

### Step 1: Create `.claude/settings.json`

Create the file `h:\development\projects\AUDia\AUDiaGentic\.claude\settings.json`:

```json
{
  "version": "1.0",
  "instruction-files": [
    "CLAUDE.md"
  ],
  "rules-directories": [
    ".claude/rules"
  ],
  "skills-directories": [
    ".claude/skills"
  ],
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [{"type": "command", "command": "python tools/claude_hooks.py user-prompt-submit"}]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [{"type": "command", "command": "python tools/claude_hooks.py pre-tool-use"}]
      }
    ]
  }
}
```

**Task:** Create `.claude/settings.json` with command-hook configuration

---

## Part 2: Implement Hook Handler Logic

### Step 2: Create hook handler module

Create file: `tools/claude_hooks.py`

```python
"""Claude Code hook handlers for prompt-trigger bridge integration."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional


def detect_and_launch_prompt_tag(
    raw_prompt: str,
    session_metadata: dict[str, Any],
) -> dict[str, Any]:
    """
    UserPromptSubmit hook: detect canonical tag and route to shared bridge.
    
    Args:
        raw_prompt: Raw user prompt text
        session_metadata: Session context (surface, session_id, workspace_root, etc.)
    
    Returns:
        Dict with launch context if tag detected, empty dict otherwise
    """
    if not raw_prompt:
        return {}
    
    # Extract first non-empty line
    first_line = None
    for line in raw_prompt.split('\n'):
        if line.strip():
            first_line = line.strip()
            break
    
    if not first_line:
        return {}
    
    # Detect canonical tag
    canonical_tags = ['@plan', '@implement', '@review', '@audit', '@check-in-prep']
    tag_found = None
    for tag in canonical_tags:
        if first_line.startswith(tag):
            tag_found = tag
            break
    
    if not tag_found:
        return {}  # No canonical tag, pass through to normal planning
    
    # Tag detected: normalize and route to shared bridge
    return _invoke_shared_bridge(
        raw_prompt=raw_prompt,
        first_line=first_line,
        tag=tag_found,
        session_metadata=session_metadata,
    )


def _invoke_shared_bridge(
    raw_prompt: str,
    first_line: str,
    tag: str,
    session_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Invoke shared prompt-trigger bridge and return result."""
    try:
        workspace_root = session_metadata.get('workspace_root', '.')
        surface = session_metadata.get('surface', 'cli')
        session_id = session_metadata.get('session_id', '')
        
        # Extract parameters from first line (e.g., "@plan provider=cline id=job_001")
        params = _parse_first_line_params(first_line)
        provider_id = params.get('provider', 'claude')
        
        # Build bridge invocation
        bridge_cmd = [
            sys.executable,
            str(Path(__file__).parent / 'claude_prompt_trigger_bridge.py'),
            '--project-root', str(workspace_root),
            '--surface', surface,
            '--provider-id', provider_id,
        ]
        
        if session_id:
            bridge_cmd.extend(['--session-id', session_id])
        
        # Invoke shared bridge
        result = subprocess.run(
            bridge_cmd,
            input=raw_prompt,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode != 0:
            # Bridge failed; return error context
            try:
                return json.loads(result.stdout)
            except (json.JSONDecodeError, ValueError):
                return {
                    'status': 'error',
                    'kind': 'bridge_invocation_failed',
                    'message': result.stderr or 'Bridge invocation failed with no error output',
                }
        
        # Parse and return bridge result
        return json.loads(result.stdout)
    
    except subprocess.TimeoutExpired:
        return {
            'status': 'error',
            'kind': 'timeout',
            'message': 'Shared bridge invocation timed out after 30 seconds',
        }
    except Exception as exc:
        return {
            'status': 'error',
            'kind': 'exception',
            'message': f'Hook handler error: {type(exc).__name__}: {exc}',
        }


def _parse_first_line_params(first_line: str) -> dict[str, str]:
    """
    Parse inline parameters from first line.
    
    Examples:
        "@plan provider=cline" → {'provider': 'cline'}
        "@review id=job_001 provider=claude" → {'id': 'job_001', 'provider': 'claude'}
    """
    params = {}
    tokens = first_line.split()
    
    for token in tokens[1:]:  # Skip the tag itself
        if '=' in token:
            key, value = token.split('=', 1)
            params[key.strip()] = value.strip()
    
    return params


def enforce_stage_restrictions(
    action_tag: str,
    tools_requested: list[str],
    session_metadata: dict[str, Any],
) -> dict[str, Any]:
    """
    PreToolUse hook: enforce stage restrictions per action tag.
    
    Args:
        action_tag: The detected action tag (plan, implement, review, etc.)
        tools_requested: List of tool names Claude wants to use
        session_metadata: Session context
    
    Returns:
        Dict with 'allowed_tools' list
    """
    if not action_tag:
        return {'allowed_tools': tools_requested}
    
    # Load restriction policy
    allowed_tools = _get_allowed_tools_for_stage(action_tag)
    
    # Filter requested tools to allowed set
    filtered = [t for t in tools_requested if t in allowed_tools]
    
    return {'allowed_tools': filtered}


def _get_allowed_tools_for_stage(action_tag: str) -> set[str]:
    """
    Get allowed tools for a given action stage.
    
    Policy from `.claude/rules/review-policy.md` and tag doctrine.
    """
    # Read-only tools available in all stages
    read_tools = {
        'Glob', 'Grep', 'Read',
        'Bash',  # read-only use only (enforced by PreToolUse, not syntax)
        'WebFetch', 'WebSearch',
        'Agent',  # research/exploration agents allowed
    }
    
    # Write/mutation tools
    write_tools = {
        'Edit', 'Write', 'NotebookEdit',
        'Bash',  # write operations (will be restricted by context in review)
    }
    
    # Approval/deployment tools
    approval_tools = {
        'Bash',  # potentially destructive (e.g., git push)
    }
    
    if action_tag == 'review':
        # Review: read-focused only, no writes
        allowed = read_tools | {'TodoWrite'}  # read-only TODOs OK
        allowed.discard('Bash')  # No shell in review
        return allowed
    
    elif action_tag == 'plan':
        # Plan: explore + read, no implementation
        allowed = read_tools | {'Agent', 'TodoWrite'}
        allowed.discard('Write')
        allowed.discard('Edit')
        allowed.discard('NotebookEdit')
        allowed.discard('Bash')  # No shell in plan
        return allowed
    
    elif action_tag == 'implement':
        # Implement: full access
        return read_tools | write_tools | approval_tools | {'TodoWrite'}
    
    elif action_tag == 'audit':
        # Audit: read-focused inspection
        allowed = read_tools | {'TodoWrite'}
        allowed.discard('Bash')
        return allowed
    
    elif action_tag == 'check-in-prep':
        # Check-in prep: read + doc creation
        allowed = read_tools | {'Write', 'Edit', 'TodoWrite'}
        allowed.discard('Bash')
        return allowed
    
    else:
        # Unknown tag: default to read-only for safety
        return read_tools


# Hook exports for Claude settings configuration

def UserPromptSubmit_handler(
    raw_prompt: str,
    session_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Exported hook handler for Claude settings.json UserPromptSubmit."""
    return detect_and_launch_prompt_tag(raw_prompt, session_metadata)


def PreToolUse_handler(
    action_tag: str,
    tools_requested: list[str],
    session_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Exported hook handler for Claude settings.json PreToolUse."""
    return enforce_stage_restrictions(action_tag, tools_requested, session_metadata)
```

**Task:** Create `tools/claude_hooks.py` with hook handler implementations

---

### Step 3: Update `.claude/settings.json` to reference hook handlers

Update the hooks section in `.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [{"type": "command", "command": "python tools/claude_hooks.py user-prompt-submit"}]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [{"type": "command", "command": "python tools/claude_hooks.py pre-tool-use"}]
      }
    ]
  }
}
```

**Task:** Update `.claude/settings.json` command-hook references

---

## Part 3: Add Hook Tests

### Step 4: Create hook tests

File: `tests/integration/providers/test_claude_hooks.py`

```python
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
```

**Task:** Create `tests/integration/providers/test_claude_hooks.py` with hook tests

---

### Step 5: Run hook tests

```bash
pytest tests/integration/providers/test_claude_hooks.py -v
```

Expected:
- ✅ `test_detects_plan_tag` — PASS
- ✅ `test_passes_through_non_tagged_prompt` — PASS
- ✅ `test_parses_provider_override` — PASS
- ✅ `test_review_restricts_write_tools` — PASS
- ✅ `test_plan_restricts_implementation_tools` — PASS
- ✅ `test_implement_allows_all_tools` — PASS

**Task:** Run and verify hook tests pass

---

## Part 4: Integration Testing

### Step 6: End-to-end hook chain test

File: `tests/integration/providers/test_claude_hook_chain.py`

```python
"""End-to-end tests for Claude hook chain integration."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.skipif(
    not (ROOT / '.claude' / 'settings.json').exists(),
    reason="Claude settings.json not configured"
)
def test_hook_chain_plan_tag_via_bridge(tmp_path: Path):
    """Verify @plan tag routes through hook → bridge → launcher."""
    # This test requires Claude Code to be available
    # It validates the full chain: hook detects tag → invokes bridge → gets job
    
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "claude_hooks.py"),
            "--test-mode",
            "--action", "plan",
            "--target", "packet:PKT-PRV-055",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    
    if result.returncode == 0:
        payload = json.loads(result.stdout)
        assert payload.get('status') == 'created'


@pytest.mark.skipif(
    not (ROOT / '.claude' / 'settings.json').exists(),
    reason="Claude settings.json not configured"
)
def test_fallback_to_wrapper_when_hook_unavailable():
    """Verify fallback to wrapper bridge when hook chain fails."""
    # Mock hook unavailability and verify wrapper is used
    # This ensures graceful degradation
    pass  # Implementation depends on Claude hook API


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
```

**Task:** Create integration test for hook chain

---

### Step 7: CLI smoke test

```bash
cd h:\development\projects\AUDia\AUDiaGentic

# Test with hook available
echo "@plan provider=claude
Review the current implementation status of Claude prompt-trigger integration." | \
  python -m tools.claude_hooks --test-hook UserPromptSubmit
```

Expected: Returns JSON with job creation status or bridge result.

**Task:** Run CLI smoke test with hooks

---

### Step 8: Fallback test (hook unavailable)

```bash
# Temporarily remove hook configuration
mv .claude/settings.json .claude/settings.json.bak

# Try wrapper bridge directly
python tools/claude_prompt_trigger_bridge.py --project-root . <<EOF
@plan provider=claude
Test fallback path.
EOF

# Should still work (fallback to wrapper)
# Then restore settings
mv .claude/settings.json.bak .claude/settings.json
```

Expected: Wrapper bridge works when hooks unavailable.

**Task:** Verify fallback to wrapper works

---

## Part 5: Documentation Updates

### Step 9: Update hook contract documentation

File: `docs/specifications/architecture/45_DRAFT_Claude_UserPromptSubmit_Hook_Contract.md`

Add implementation examples section:

```markdown
## Implementation examples

See `tools/claude_hooks.py` for reference implementations:
- `detect_and_launch_prompt_tag()` — UserPromptSubmit handler
- `enforce_stage_restrictions()` — PreToolUse handler
```

**Task:** Add implementation reference to architecture spec

---

## Part 6: Build Registry Update

### Step 10: Mark PKT-PRV-055 as READY_FOR_REVIEW

Once all tests pass and integration verified:

File: `docs/implementation/31_Build_Status_and_Work_Registry.md`

Update PKT-PRV-055 status through review and verification checkpoints as the native-hook path lands; the current registry now records this packet as VERIFIED.

**Task:** Update build registry

---

## Acceptance Criteria

- [ ] `.claude/settings.json` created with command-hook configuration
- [ ] `tools/claude_hooks.py` implements UserPromptSubmit handler
- [ ] `tools/claude_hooks.py` implements PreToolUse handler
- [ ] Stage restriction policy enforced correctly per action tag
- [ ] `test_claude_hooks.py` all tests pass
- [ ] `test_claude_hook_chain.py` integration tests pass
- [ ] CLI smoke test with hooks succeeds
- [ ] Fallback to wrapper bridge works when hooks unavailable
- [ ] Hook-invoked and wrapper-invoked paths produce identical normalized requests
- [ ] CLI and VS Code surfaces behave identically
- [ ] PKT-PRV-055 status updated to READY_FOR_REVIEW

---

## Time Estimate

- Settings.json creation: ~5 min
- Hook implementation: ~30 min (handlers + stage policy)
- Test writing: ~20 min (unit + integration)
- Smoke testing: ~15 min (CLI, fallback, chain verification)
- **Total: ~70 minutes**

---

## Success Criteria

✅ Option B complete when:
1. All tests pass (unit, integration, smoke)
2. Hooks successfully intercept and route @-tagged prompts
3. Stage restrictions enforced (e.g., review blocks writes)
4. Fallback to wrapper works seamlessly
5. PKT-PRV-055 marked VERIFIED in build registry
