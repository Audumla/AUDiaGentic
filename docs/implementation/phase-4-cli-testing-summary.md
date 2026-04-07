# Phase 4 CLI Testing Summary

## Test Date: 2026-04-06

## Test Environment
- OS: Windows 11
- Python: 3.13
- Working Directory: H:\development\projects\AUDia\AUDiaGentic

## Provider Status

| Provider | CLI Available | Adapter Works | Notes |
|----------|---------------|---------------|-------|
| **Codex** | ✓ | ✓ | Fully functional; reliable for testing |
| **Cline** | ✓ | ✓ | Works but slow; outputs NDJSON |
| **Qwen** | ✓ | ✗ | CLI available but adapter uses wrong flags; no output |
| **Claude** | ✓ | ✗ | Requires git-bash on Windows (not installed) |
| **Gemini** | ✓ | ✗ | Quota exhausted on test account |
| **opencode** | N/A | N/A | Skipped (current execution environment) |

## Test Results

### Codex Tests
```
Test: 2+2 = ?
Result: 4 ✓

Test: 15 × 17 = ?
Result: 255 ✓

Test: Capital of France?
Result: Paris ✓
```

### Bridge Tests
```
Test: @ag-plan tag routing
Result: Job created successfully ✓
Provider routing: Works correctly ✓
```

## Issues Found

### 1. Qwen Adapter - Incorrect CLI Flags
**File**: `src/audiagentic/execution/providers/adapters/qwen.py`

**Problem**: Adapter uses `-p` and `-o` flags which don't exist in Qwen CLI.

**Current code**:
```python
command = [
    executable,
    "-p", prompt,
    "-o", str(output_format),
]
```

**Fix applied**: Changed to use positional arguments:
```python
command = [executable]
if approval_mode == "yolo":
    command.append("--yolo")
if default_model:
    command.extend(["-m", str(default_model)])
command.append(prompt)  # Positional argument
```

### 2. Claude on Windows - Requires git-bash
**Issue**: Claude CLI on Windows requires git-bash to be installed.

**Workaround**: Set `CLAUDE_CODE_GIT_BASH_PATH` environment variable or install Git for Windows.

### 3. Gemini - Quota Exhausted
**Issue**: Test account has exhausted Gemini API quota.

**Workaround**: Use free tier model (`gemini-2.5-flash`) or fallback to other providers.

## Recommendations

1. **For CI/CD testing**: Use Codex as primary test provider (reliable)
2. **For production**: Implement provider fallback strategy (see spec 55)
3. **For Qwen**: Test adapter fix after deployment
4. **For Claude**: Document Windows setup requirements

## Files Modified

1. `src/audiagentic/streaming/provider_streaming.py` - Timeout handling fix
2. `src/audiagentic/streaming/sinks.py` - Per-path event write locks
3. `src/audiagentic/execution/providers/adapters/qwen.py` - CLI flag fix
4. `.audiagentic/project.yaml` - Enabled adhoc target for testing
5. `docs/specifications/architecture/55_Provider_Availability_and_Quota_Handling.md` - New spec

## Next Steps

1. Test Qwen adapter fix
2. Implement provider health check
3. Add fallback routing logic
4. Document Claude Windows setup
