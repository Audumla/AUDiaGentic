# Provider Architecture Review

> **Updated for v3 structural refactor.** Provider code now lives under `interoperability/providers/`.

## Executive Summary

This document reviews the AUDiaGentic provider architecture against the following principles:

1. **Modularity**: Each provider's implementation is isolated to its own adapter file
2. **Separation of Concerns**: Shared code is generic; provider-specific code is isolated
3. **Schema Validation**: All configuration is validated against JSON schemas
4. **Test Coverage**: Comprehensive testing for each component

## Architecture Overview

```
src/audiagentic/
├── foundation/
│   ├── config/
│   │   ├── provider_config.py      # Shared: Config loading/validation
│   │   └── provider_catalog.py     # Shared: Model catalog management
│   └── contracts/
│       ├── schemas/                # Shared: JSON schemas
│       │   ├── provider-config.schema.json
│       │   ├── project-config.schema.json
│       │   └── ...
│       └── schema_registry.py      # Shared: Schema resolution
├── interoperability/
│   ├── providers/
│   │   ├── adapters/               # Provider-specific implementations
│   │   │   ├── codex.py            # Codex-specific
│   │   │   ├── cline.py            # Cline-specific
│   │   │   ├── claude.py           # Claude-specific
│   │   │   ├── gemini.py           # Gemini-specific
│   │   │   ├── qwen.py             # Qwen-specific
│   │   │   ├── opencode.py         # opencode-specific
│   │   │   └── ...
│   │   ├── execution.py            # Provider dispatch
│   │   ├── selection.py            # Provider selection logic
│   │   ├── health.py               # Provider health checks
│   │   ├── models.py               # Model catalog types
│   │   └── status.py               # Provider status reporting
│   └── protocols/
│       └── streaming/              # Generic streaming primitives
│           ├── provider_streaming.py   # Command execution
│           ├── sinks.py                # Stream sinks
│           └── completion.py           # Result normalization
```

## 1. Modularity Assessment

### Provider Isolation ✓

Each provider has its own file in `src/audiagentic/interoperability/providers/adapters/`:

| Provider | File | Lines | Owner |
|----------|------|-------|-------|
| Codex | `codex.py` | ~350 | Provider team |
| Cline | `cline.py` | ~330 | Provider team |
| Claude | `claude.py` | ~345 | Provider team |
| Gemini | `gemini.py` | ~340 | Provider team |
| Qwen | `qwen.py` | ~275 | Provider team |
| opencode | `opencode.py` | ~330 | Provider team |

**Verification**: No cross-provider imports found.

### Shared Code Isolation ✓

Shared code in `interoperability/protocols/streaming/` and `foundation/config/` does not reference specific providers.

## 2. Separation of Concerns

### Shared Components (Generic)

| Component | Purpose | Provider-Agnostic |
|-----------|---------|-------------------|
| `StreamSink` protocol | Stream output interface | ✓ |
| `InMemorySink` | In-memory capture | ✓ |
| `ConsoleSink` | Console output | ✓ |
| `RawLogSink` | File logging | ✓ |
| `NormalizedEventSink` | NDJSON events | ✓ |
| `run_streaming_command()` | Command execution | ✓ |
| `ProviderCompletion` | Result normalization | ✓ |
| `validate_provider_config()` | Config validation | ✓ |

### Provider-Specific Components

| Provider | Event Extractor | Stream Builder | Notes |
|----------|-----------------|----------------|-------|
| Codex | `CodexEventExtractor` | `build_codex_stream_sinks()` | Milestone parsing |
| Cline | `ClineEventExtractor` | `build_cline_stream_sinks()` | NDJSON parsing |
| Claude | `ClaudeEventExtractor` | `build_claude_stream_sinks()` | Stream-json parsing |
| Gemini | `GeminiEventExtractor` | `build_gemini_stream_sinks()` | Plain text |
| Qwen | `QwenEventExtractor` | `build_qwen_stream_sinks()` | Plain text |
| opencode | `OpencodeEventExtractor` | `build_opencode_stream_sinks()` | NDJSON parsing |

**Key Design**: Each provider implements:
1. Event extractor (parses provider-specific output format)
2. Stream builder (configures sinks for that provider)
3. Completion parser (extracts structured results)

All using the same shared interfaces.

### Cross-Layer Seam: Gemini Adapter

`interoperability/providers/adapters/gemini.py` imports from `execution.jobs.prompt_launch` and `execution.jobs.prompt_parser`. This is an intentional one-way dependency: `interoperability → execution`. It is documented and allowed in the dependency rules.

## 3. Configuration Architecture

### Configuration Files

| File | Purpose | Schema |
|------|---------|--------|
| `.audiagentic/providers.yaml` | Provider configuration | `provider-config.schema.json` |
| `.audiagentic/project.yaml` | Project settings | `project-config.schema.json` |
| `.audiagentic/prompt-syntax.yaml` | Tag/alias definitions | `prompt-syntax.schema.json` |

### Schema Validation ✓

All configuration is validated against JSON schemas in `foundation/contracts/schemas/`:

```python
# src/audiagentic/foundation/config/provider_config.py
def load_provider_config(project_root: Path) -> dict[str, Any]:
    payload = _load_yaml(path)
    issues = validate_provider_config(payload)  # Schema validation
    if issues:
        raise AudiaGenticError(...)
    return payload
```

### Provider Configuration Structure

```yaml
providers:
  <provider-id>:
    enabled: boolean
    install-mode: string
    access-mode: enum
    default-model: string
    timeout-seconds: integer
    model-aliases: object
    catalog-refresh: object
    prompt-surface: object
    execution-policy: object
      output-format: enum
      permission-mode: enum
      safety-mode: enum
      auto-approve: boolean
      full-auto: boolean
      ephemeral: boolean
      target-type: string
      timeout-seconds: integer
```

## 4. Test Coverage

### Unit Tests

| Component | Test File | Coverage |
|-----------|-----------|----------|
| Streaming sinks | `tests/unit/streaming/test_sinks.py` | 23 tests |
| Completion | `tests/unit/streaming/test_completion.py` | 19 tests |
| Provider config | `tests/unit/config/test_provider_config.py` | ✓ |

### Integration Tests

| Provider | Test File | Status |
|----------|-----------|--------|
| Codex | `tests/integration/providers/test_codex.py` | ✓ 2 tests |
| Cline | `tests/integration/providers/test_cline.py` | ✓ 2 tests |
| Claude | `tests/integration/providers/test_claude.py` | ✓ 2 tests |
| Claude hooks | `tests/integration/providers/test_claude_hooks.py` | ✓ 7 tests |
| Gemini | `tests/integration/providers/test_gemini.py` | ✓ 2 tests |
| Qwen | `tests/integration/providers/test_qwen.py` | ✓ 2 tests |
| opencode | `tests/integration/providers/test_opencode.py` | ✓ 2 tests |

## 5. Verification Commands

### Check for Cross-Provider Dependencies

```bash
# Should return no results
grep -l "from.*adapters\." src/audiagentic/interoperability/providers/adapters/*.py

# Should return no provider-specific code
grep -E "(codex|cline|claude|gemini|qwen|opencode)" \
    src/audiagentic/interoperability/protocols/streaming/*.py
```

### Validate Configuration

```bash
python -c "
from pathlib import Path
from audiagentic.foundation.config.provider_config import load_provider_config
config = load_provider_config(Path.cwd())
print('Config valid:', list(config['providers'].keys()))
"
```

### Run Tests

```bash
python -m pytest tests/unit/streaming/ -q
python -m pytest tests/integration/providers/ -q
python -m pytest tests/ -q --ignore=tests/e2e/
```

## 6. Conclusion

### Architecture Principles Compliance

| Principle | Status | Notes |
|-----------|--------|-------|
| Modularity | ✓ | Each provider isolated to its adapter file |
| Separation of Concerns | ✓ | Shared code is generic |
| Schema Validation | ✓ | All config validated via foundation/contracts |
| Test Coverage | ✓ | 54+ tests passing |

### Key Strengths

1. **Clean separation**: Provider-specific code never leaks into shared components
2. **Extensible**: Adding new providers only requires a new adapter file
3. **Validated**: Schema validation catches configuration errors early
4. **Tested**: Comprehensive test coverage for core functionality

---

**Review Date**: 2026-04-12 (updated for v3 structural refactor)
