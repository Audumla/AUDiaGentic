# Provider Availability and Quota Handling Specification

## Overview

This document specifies how AUDiaGentic handles provider availability issues including:
- Quota exhaustion
- API rate limiting  
- Temporary unavailability
- Model switching fallbacks

## Problem Statement

During CLI testing, the following issues were observed:

| Provider | Issue | Details |
|----------|-------|---------|
| Qwen | No output | CLI runs but produces no visible output; may be API/model issue |
| Codex | Works | Returns correct results (tested: 2+2=4, 15×17=255) |
| Cline | Works (slow) | Outputs NDJSON; requires parsing for completion |
| Claude | Requires git-bash | Windows requires git-bash; not installed in test environment |
| Gemini | Quota exhausted | "You have exhausted your capacity on this model" |

## Specification

### 1. Provider Health Check

Before routing to a provider, perform a health check:

```yaml
provider-health:
  check-interval-seconds: 300  # Check every 5 minutes
  failure-threshold: 3         # Number of failures before marking unhealthy
  recovery-threshold: 2        # Number of successes before marking healthy
```

### 2. Quota/Rate Limit Detection

Detect quota/rate limit errors by matching error patterns:

```yaml
quota-error-patterns:
  gemini:
    - "exhausted your capacity"
    - "quota exceeded"
    - "429"
  openai:
    - "rate limit exceeded"
    - "quota exceeded"
    - "429"
  anthropic:
    - "rate_limit"
    - "overloaded"
```

### 3. Fallback Strategy

When a provider is unavailable, try fallback providers in order:

```yaml
fallback-strategy:
  mode: "round-robin"  # or "priority", "least-used"
  providers:
    - codex      # Primary (reliable, tested)
    - cline      # Secondary (works but slow)
    - qwen       # Tertiary (free but may have issues)
    - gemini     # Quaternary (quota issues)
    - claude     # Last resort (requires setup)
```

### 4. Model Switching

When a specific model is unavailable, try alternative models:

```yaml
model-fallbacks:
  gemini:
    primary: gemini-2.5-pro
    fallbacks:
      - gemini-2.5-flash  # Free tier
      - gemini-1.5-flash  # Older but available
  openai:
    primary: gpt-5.4
    fallbacks:
      - gpt-5.4-mini
      - gpt-4o-mini
```

### 5. Error Response Format

When provider fails, return structured error:

```json
{
  "status": "provider-unavailable",
  "provider-id": "gemini",
  "error": {
    "code": "PROVIDER-QUOTA-EXHAUSTED",
    "message": "Gemini quota exhausted",
    "retry-after-seconds": 24,
    "fallback-available": true,
    "suggested-fallback": "codex"
  }
}
```

### 6. Provider Status Tracking

Maintain provider status in runtime:

```yaml
# .audiagentic/runtime/provider-status.json
{
  "updated-at": "2026-04-06T00:00:00Z",
  "providers": {
    "codex": {"status": "healthy", "last-check": "...", "consecutive-failures": 0},
    "gemini": {"status": "unhealthy", "last-check": "...", "consecutive-failures": 3, "reason": "quota-exhausted"},
    "qwen": {"status": "degraded", "last-check": "...", "consecutive-failures": 1, "reason": "no-output"}
  }
}
```

## Implementation Notes

### CLI Command Fixes Needed

1. **Qwen adapter**: Uses incorrect flags (`-p`, `-o`). Qwen CLI uses positional arguments.
2. **Claude adapter**: Requires git-bash on Windows; needs environment variable configuration.

### Testing Recommendations

1. Use Codex for most automated tests (reliable)
2. Use Cline for NDJSON parsing tests
3. Skip Qwen/Gemini in CI until issues resolved
4. Claude requires Windows git-bash setup

## Known Issues

| Issue | Provider | Status | Workaround |
|-------|----------|--------|------------|
| No output | Qwen | Open | Use Codex instead |
| Quota exhausted | Gemini | Open | Use free tier model or fallback |
| Requires git-bash | Claude (Windows) | Open | Install Git for Windows or use WSL |
| Slow response | Cline | Known | Increase timeout, use for non-urgent tasks |
