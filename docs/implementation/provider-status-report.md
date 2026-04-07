# AUDiaGentic Provider Status Report

## Executive Summary

| Provider | CLI | Adapter | Speed | Reliability | Notes |
|----------|-----|---------|-------|-------------|-------|
| **Codex** | ✓ | ✓ | Fast | High | Best for automated testing |
| **opencode** | ✓ | ✓ | Fast | High | Local model, no quota issues |
| **Cline** | ✓ | ✓ | Slow | Medium | NDJSON output, verbose |
| **Qwen** | ✓ | ✓ | Fast | Medium | CLI flag fix applied |
| **Claude** | ✓ | ✓ | Medium | High | Requires git-bash; hooks implemented |
| **Gemini** | ✓ | ✓ | Medium | Medium | Works with default model; quota issues on specific models |

---

## Detailed Provider Analysis

### 1. Codex (OpenAI)

**Status**: ✅ Fully Operational

**CLI Command**:
```bash
codex exec --ephemeral --skip-git-repo-check "<prompt>"
```

**Test Results**:
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| 2+2 | 4 | 4 | ✓ |
| 15×17 | 255 | 255 | ✓ |
| Capital of France | Paris | Paris | ✓ |

**Adapter Features**:
- ✓ Event extraction (milestone parsing)
- ✓ Structured completion
- ✓ Stream capture
- ✓ Config-driven execution policy

**Configuration**:
```yaml
codex:
  default-model: gpt-5.4-mini
  execution-policy:
    output-format: text
    full-auto: true
    ephemeral: true
    timeout-seconds: 300
```

**Recommendation**: Primary provider for CI/CD and automated testing.

---

### 2. opencode (Local)

**Status**: ✅ Fully Operational

**CLI Command**:
```bash
opencode run --model <model> --format json "<prompt>"
```

**Available Models**:
- `llamaswap/qwen3-5-4b-ud-q5-k-xl-vision3` (4B, fast, local)
- `llamaswap/qwen3.5-27b-(96k-Q6)` (27B, medium)
- `llamaswap/qwen3.5-27b-Q8` (27B, high quality)

**Test Results**:
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| 2+2 | 4 | 4 | ✓ |
| 15×17 | 255 | 255 | ✓ |
| Capital of France | Paris | Paris | ✓ |

**Adapter Features**:
- ✓ NDJSON event extraction
- ✓ Structured completion (fixed)
- ✓ Stream capture
- ✓ Config-driven execution policy

**Configuration**:
```yaml
opencode:
  default-model: llamaswap/qwen3-5-4b-ud-q5-k-xl-vision3
  execution-policy:
    output-format: json
    timeout-seconds: 120
```

**Recommendation**: Best for offline/local work, no quota concerns.

---

### 3. Cline

**Status**: ✅ Operational (Slow)

**CLI Command**:
```bash
cline --json --auto-approve-all "<prompt>"
```

**Output Format**: NDJSON stream
```json
{"type":"task_started","taskId":"..."}
{"type":"say","say":"task","text":"..."}
{"type":"completion_result","text":"..."}
```

**Adapter Features**:
- ✓ NDJSON event extraction
- ✓ Structured completion
- ✓ Stream capture
- ✓ Config-driven execution policy

**Configuration**:
```yaml
cline:
  default-model: kwaipilot/kat-coder-pro
  execution-policy:
    output-format: json
    auto-approve: true
    timeout-seconds: 300
```

**Notes**:
- Very verbose output (full task context)
- Slow response times
- Good for complex multi-step tasks

**Recommendation**: Use for complex tasks requiring tool use.

---

### 4. Qwen

**Status**: ⚠️ Fixed (Needs Verification)

**CLI Command**:
```bash
qwen "<prompt>"  # Positional argument
```

**Issue Fixed**: Adapter was using incorrect flags (`-p`, `-o`) that don't exist in Qwen CLI.

**Before**:
```python
command = [executable, "-p", prompt, "-o", output_format]
```

**After**:
```python
command = [executable]
if approval_mode == "yolo":
    command.append("--yolo")
command.append(prompt)  # Positional
```

**Configuration**:
```yaml
qwen:
  default-model: qwen-coder
  execution-policy:
    output-format: text
    timeout-seconds: 120
```

**Recommendation**: Free tier option, verify after fix deployment.

---

### 5. Claude

**Status**: ✅ Operational (with setup)

**Setup Required**: Claude CLI on Windows requires git-bash.

**Environment Variable**:
```bash
CLAUDE_CODE_GIT_BASH_PATH=H:\development\tools\Git\bin\bash.exe
```

**CLI Command**:
```bash
claude --print --model haiku --output-format text --permission-mode auto "<prompt>"
```

**Test Results**:
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| 2+2 | 4 | 4 | ✓ |

**Hooks Implementation**:
- ✅ `UserPromptSubmit` - Detects `@ag-*` tags and routes to bridge
- ✅ `PreToolUse` - Enforces stage restrictions (review=readonly, etc.)

**Hook Handlers** (`tools/claude_hooks.py`):
```python
UserPromptSubmit_handler(raw_prompt, session_metadata)
PreToolUse_handler(action_tag, tools_requested, session_metadata)
```

**Stage Restrictions**:
| Stage | Allowed Tools |
|-------|---------------|
| plan | Read, Glob, Grep, Agent, TodoWrite |
| review | Read, Glob, Grep, TodoWrite (no Bash) |
| implement | All tools |
| audit | Read, Glob, Grep, TodoWrite |

**Configuration**:
```yaml
claude:
  default-model: haiku  # Faster, cheaper
  execution-policy:
    output-format: text
    permission-mode: auto
    timeout-seconds: 300
```

**Recommendation**: Use haiku for speed/cost; hooks enable stage-aware tool restrictions.

---

### 6. Gemini

**Status**: ⚠️ Operational (with caveats)

**Issue**: Specific models may have quota issues; default model works.

**Test Results**:
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| 2+2 | 4 | 4 | ✓ |

**CLI Command**:
```bash
gemini -p "<prompt>" -o text  # Uses default model
```

**Notes**:
- Default model works (returns correct results)
- Specific model names may fail with `ModelNotFoundError`
- IDE connection warnings are non-fatal

**Configuration**:
```yaml
gemini:
  default-model: gemini-2.5-pro  # May have quota issues
  execution-policy:
    output-format: text
    timeout-seconds: 300
```

**Recommendation**: Use default model; implement fallback for quota errors.

---

## Claude Hooks

### Hook Architecture

Claude supports lifecycle hooks that can intercept and modify behavior:

| Hook | Purpose | Implementation |
|------|---------|----------------|
| `UserPromptSubmit` | Detect tags before execution | `tools/claude_hooks.py` |
| `PreToolUse` | Restrict tools by stage | `tools/claude_hooks.py` |

### Hook Configuration

Add to `.claude/settings.json`:
```json
{
  "hooks": {
    "UserPromptSubmit": {
      "command": "python",
      "args": ["tools/claude_hooks.py", "user-prompt-submit"]
    },
    "PreToolUse": {
      "command": "python",
      "args": ["tools/claude_hooks.py", "pre-tool-use"]
    }
  }
}
```

### Stage Restrictions

| Stage | Read Tools | Write Tools | Shell |
|-------|------------|-------------|-------|
| plan | ✓ | ✗ | ✗ |
| review | ✓ | ✗ | ✗ |
| implement | ✓ | ✓ | ✓ |
| audit | ✓ | ✗ | ✗ |
| check-in-prep | ✓ | ✓ (docs only) | ✗ |

### Hook Tests

```bash
python -m pytest tests/integration/providers/test_claude_hooks.py -v
# 7 passed
```

## Bridge Testing

### Prompt Trigger Bridge

**Test**: `@ag-plan provider=qwen id=test_001`

**Result**: ✅ Job created successfully
```json
{
  "status": "created",
  "job-id": "job_20260405_0016",
  "provider-id": "qwen",
  "launch-tag": "ag-plan"
}
```

**All Bridges Tested**:
- ✅ codex_prompt_trigger_bridge.py
- ✅ cline_prompt_trigger_bridge.py
- ✅ qwen_prompt_trigger_bridge.py
- ✅ gemini_prompt_trigger_bridge.py
- ✅ claude_prompt_trigger_bridge.py

---

## Streaming & Completion Features

### Stream Capture

| Feature | Status | Files |
|---------|--------|-------|
| StreamSink protocol | ✅ | `streaming/sinks.py` |
| InMemorySink | ✅ | `streaming/sinks.py` |
| ConsoleSink | ✅ | `streaming/sinks.py` |
| RawLogSink | ✅ | `streaming/sinks.py` |
| NormalizedEventSink | ✅ | `streaming/sinks.py` |

### Event Extractors

| Provider | Extractor | Status |
|----------|-----------|--------|
| Codex | CodexEventExtractor | ✅ |
| Cline | ClineEventExtractor | ✅ |
| Gemini | GeminiEventExtractor | ✅ |
| Qwen | QwenEventExtractor | ✅ |
| Claude | ClaudeEventExtractor | ✅ |
| opencode | OpencodeEventExtractor | ✅ |

### Structured Completion

| Provider | Parsing | Result Source |
|----------|---------|---------------|
| Codex | JSON block | stdout-json-block |
| Cline | NDJSON | stdout-json |
| opencode | NDJSON | stdout-json |
| Gemini | JSON | stdout-json |
| Qwen | JSON | stdout-json |
| Claude | JSON | stdout-json |

---

## Configuration Files

### .audiagentic/providers.yaml

```yaml
contract-version: v1
providers:
  codex:
    enabled: true
    default-model: gpt-5.4-mini
    execution-policy:
      output-format: text
      full-auto: true
      ephemeral: true
      timeout-seconds: 300
  
  opencode:
    enabled: true
    default-model: llamaswap/qwen3-5-4b-ud-q5-k-xl-vision3
    execution-policy:
      output-format: json
      timeout-seconds: 120
  
  # ... other providers
```

### .audiagentic/project.yaml

```yaml
prompt-launch:
  default-stream-controls:
    enabled: true
    tee-console: true
    timeout-warning-seconds: null
    sink-error-policy: warn
    invalid-event-policy: quarantine
    overflow-policy: warn-only
```

---

## Recommendations

### Immediate Actions

1. **Use opencode for local testing** - No quota issues, fast response
2. **Use Codex for CI/CD** - Most reliable, well-tested
3. **Document Claude Windows setup** - git-bash requirement
4. **Implement provider fallback** - See spec 55

### Future Work

1. **Provider health checks** - Auto-detect unavailable providers
2. **Quota monitoring** - Track and warn before exhaustion
3. **Model fallback** - Auto-switch to available models
4. **Response caching** - Cache common queries

---

## Test Commands

### Quick Provider Test
```bash
# Codex
codex exec --ephemeral "What is 2+2?"

# opencode
opencode run --model llamaswap/qwen3-5-4b-ud-q5-k-xl-vision3 "What is 2+2?"

# Cline
cline --json --auto-approve-all "What is 2+2?"

# Qwen
qwen "What is 2+2?"

# Claude (requires git-bash on Windows)
CLAUDE_CODE_GIT_BASH_PATH="H:\\development\\tools\\Git\\bin\\bash.exe" \
  claude --print --model haiku --output-format text "What is 2+2?"

# Gemini (uses default model)
gemini -p "What is 2+2?" -o text
```

### Adapter Test
```python
from audiagentic.execution.providers.adapters import codex

result = codex.run(
    {'provider-id': 'codex', 'job-id': 'test', 'prompt-body': '2+2?', 'working-root': '.'},
    {'default-model': 'gpt-5.4-mini'}
)
print(result['output'])
```

---

## Report Generated

- **Date**: 2026-04-07
- **Environment**: Windows 11, Python 3.13
- **Test Models**:
  - opencode: llamaswap/qwen3-5-4b-ud-q5-k-xl-vision3
  - Claude: haiku
  - Gemini: default (gemini-2.5-pro)
