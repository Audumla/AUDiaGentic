# opencode Tag Execution Implementation

## Overview

This document describes how opencode executes canonical prompt tags within the AUDiaGentic framework. opencode is classified as a **wrapper-first** provider, meaning tag recognition and normalization happen in a wrapper layer before reaching the shared bridge.

## Provider Classification

| Attribute | Value |
|-----------|-------|
| Classification | `wrapper-first` |
| Tag Recognition | Wrapper layer |
| Normalization | Shared bridge |
| Execution | opencode CLI adapter |

## Execution Flow

```
┌─────────────────────────────────────────────────────────────┐
│  User types: @ag-review provider=opencode <prompt>        │
└─────────────────────────────────┬───────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────┐
│  opencode wrapper / CLI invocation                         │
│  - Detects first line starts with @                        │
│  - Identifies canonical tag                                │
└─────────────────────────┬───────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  tools/opencode_prompt_trigger_bridge.py                   │
│  - Delegates to shared bridge                              │
└─────────────────────────┬───────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Shared prompt parser (prompt_parser.py)                   │
│  - Normalizes tag to canonical form                        │
│  - Resolves provider aliases                               │
│  - Builds launch envelope                                  │
└─────────────────────────┬───────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Job creation (prompt_launch.py)                           │
│  - Creates job record                                      │
│  - Sets initial state                                      │
└─────────────────────────┬───────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  opencode adapter (adapters/opencode.py)                   │
│  - Invokes opencode CLI                                    │
│  - Captures streaming output                               │
│  - Returns normalized result                               │
└─────────────────────────────────────────────────────────────┘
```

## Tag Support Matrix

| Tag | Supported | Notes |
|-----|-----------|-------|
| `@ag-plan` | Yes | Full support |
| `@ag-implement` | Yes | Full support |
| `@ag-review` | Yes | Full support |
| `@ag-audit` | Yes | Full support |
| `@ag-check-in-prep` | Yes | Full support |

## Provider-Specific Behavior

### Tag Recognition

opencode uses wrapper-based tag recognition:

1. User invokes opencode CLI or wrapper script
2. Wrapper reads the first non-empty line of input
3. If line starts with `@`, wrapper detects it as a tagged prompt
4. Wrapper routes through `tools/opencode_prompt_trigger_bridge.py`
5. Bridge delegates to shared parser for normalization

### Model Selection

opencode supports model selection via:

1. **Explicit model-id**: `@ag-plan provider=opencode model=<model-id>`
2. **Model alias**: `@ag-plan provider=opencode model-alias=<alias>`
3. **Default model**: Configured in `.audiagentic/providers.yaml`

Current repository note:
- the live `.audiagentic/providers.yaml` now includes the `opencode` entry and must stay aligned with adapter/runtime behavior
- provider selection and default-model resolution are therefore not yet in parity with the
  documented wrapper/bridge path

### Streaming Output

opencode adapter supports streaming output capture:

```yaml
stream-controls:
  enabled: true
  tee-console: true
```

When enabled:
- stdout captured to `.audiagentic/runtime/jobs/<job-id>/stdout.log`
- stderr captured to `.audiagentic/runtime/jobs/<job-id>/stderr.log`
- Output optionally tee'd to console

Provider-facing instruction content should ultimately come from the Phase 4.4.1 canonical
provider-function source and generated provider surfaces. opencode is not a special “no skills”
exception; it consumes the shared provider-surface model through wrapper-first execution.

## Configuration

### Required Configuration

`.audiagentic/providers.yaml`:

```yaml
providers:
  opencode:
    enabled: true
    install-mode: external-configured
    access-mode: cli
    default-model: <model-name>
    timeout-seconds: 120
    prompt-surface:
      enabled: true
      tag-syntax: prefix-token-v1
      first-line-policy: first-non-empty-line
      cli-mode: wrapper-normalize
      vscode-mode: unsupported
      settings-profile: opencode-prompt-tags-v1
```

## Smoke Test Guidance

### Test 1: Basic Tag Recognition

```bash
echo "@ag-plan provider=opencode
Plan a simple task." |     python tools/opencode_prompt_trigger_bridge.py --project-root . --surface cli
```

**Expected:** Job created with tag `ag-plan`, provider `opencode`

### Test 2: Review Tag

```bash
echo "@ag-review provider=opencode target=artifact:test.md
Review this file." |     python tools/opencode_prompt_trigger_bridge.py --project-root . --surface cli
```

**Expected:** Job created with tag `ag-review`, target type `artifact`

### Test 3: Combined Alias

```bash
echo "@agr-opc
Review the implementation." |     python tools/opencode_prompt_trigger_bridge.py --project-root . --surface cli
```

**Expected:** Job created with tag `ag-review`, provider `opencode`

## Limitations

1. **No native hook support**: opencode does not support native hooks for tag interception
2. **CLI-only**: No VS Code extension support at this time
3. **Wrapper required**: Tag recognition requires wrapper layer

## Rollback Procedure

If tag execution needs to be disabled:

1. Set `prompt-surface.enabled: false` in provider config
2. Remove wrapper script from PATH (if installed)
3. Jobs will fall back to non-tagged execution mode

## Related Documents

- [PKT-PRV-064](../../implementation/packets/phase-4/PKT-PRV-064.md) - opencode provider adapter
- [PKT-PRV-065](../../implementation/packets/phase-4/PKT-PRV-065.md) - opencode prompt-tag surface integration
- [PKT-PRV-066](../../implementation/packets/phase-4/PKT-PRV-066.md) - opencode tag execution implementation
- [PKT-PRV-067](../../implementation/packets/phase-4/PKT-PRV-067.md) - opencode prompt-trigger launch integration
