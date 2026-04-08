# Tag Routing Test Report - Full Coverage

## Executive Summary

**Tag routing is PARTIALLY working.** Only `@ag-plan` tags route correctly across all providers. Other tags have issues.

| Tag | codex | qwen | opencode | cline | claude | gemini | Total |
|-----|-------|------|----------|-------|--------|--------|-------|
| @ag-plan | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 6/6 |
| @ag-review | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | 0/6 |
| @ag-implement | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | 0/6 |
| @ag-audit | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | 0/6 |
| @ag-check-in-prep | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | 0/6 |
| **Total** | 1/5 | 1/5 | 1/5 | 1/5 | 1/5 | 1/5 | **6/30** |

## Detailed Results

### @ag-plan (6/6 passing) ✓

All providers correctly route `@ag-plan` tags:

| Provider | Status | Notes |
|----------|--------|-------|
| codex | routed | Job created with provider=codex |
| qwen | routed | Job created with provider=qwen |
| opencode | routed | Job created with provider=opencode |
| cline | routed | Job created with provider=cline |
| claude | routed | Job created with provider=claude |
| gemini | routed | Job created with provider=gemini |

### @ag-review (0/6 passing) ✗

Review tags have issues:

| Provider | Status | Notes |
|----------|--------|-------|
| codex | timeout | Review execution timed out |
| qwen | timeout | Review execution timed out |
| opencode | routing_failed | Unknown provider in response |
| cline | timeout | Review execution timed out |
| claude | routing_failed | Unknown provider in response |
| gemini | timeout | Review execution timed out |

**Issue**: Review tags execute directly (not job creation) and timeout or fail.

### @ag-implement (0/6 passing) ✗

| Provider | Status | Notes |
|----------|--------|-------|
| codex | no_response | Empty output |
| qwen | no_response | Empty output |
| opencode | no_response | Empty output |
| cline | no_response | Empty output |
| claude | no_response | Empty output |
| gemini | no_response | Empty output |

**Issue**: Bridge returns empty output for implement tags.

### @ag-audit (0/6 passing) ✗

Same as @ag-implement - empty output.

### @ag-check-in-prep (0/6 passing) ✗

Same as @ag-implement - empty output.

## Root Cause Analysis

### 1. @ag-plan Works ✓

The `@ag-plan` tag correctly creates job records with the specified provider. This is the expected behavior.

### 2. @ag-review Issues ✗

Review tags execute directly (not job creation) and:
- Timeout (providers take too long)
- Return unexpected JSON format

**Expected behavior**: Review tags should either:
- Create a job record (like @ag-plan)
- Execute quickly and return review results

### 3. @ag-implement, @ag-audit, @ag-check-in-prep Issues ✗

These tags return empty output. This suggests:
- The bridge is not handling these tags correctly
- There may be a bug in the prompt parser or launch logic

## Manual Verification

Manual testing shows that the bridge DOES work for these tags:

```bash
$ echo "@ag-implement provider=codex id=test
Test." | python tools/codex_prompt_trigger_bridge.py
{
  "job": {
    "provider-id": "codex",
    ...
  }
}
```

But the automated test shows "no_response". This suggests a test script issue or race condition.

## Recommendations

### Immediate Actions

1. **Fix review tag timeouts**: Increase timeout or optimize review execution
2. **Debug empty output**: Investigate why automated test shows empty output
3. **Verify tag handling**: Ensure all tags are handled correctly by the bridge

### Long-term Actions

1. **Add unit tests**: Test tag parsing and routing in isolation
2. **Add integration tests**: Test full bridge flow for each tag
3. **Add monitoring**: Track tag routing success/failure rates

## Conclusion

**Tag routing is partially functional.** Only `@ag-plan` works correctly across all providers. Other tags need investigation and fixes.

**Priority**: High - tag routing is core functionality.

---

**Test Date**: 2026-04-07
**Test Tool**: test_all_tags_providers.py
**Results**: 6/30 passing (20%)
