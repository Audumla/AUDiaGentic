# 18_Opencode_Plan.md

## opencode Provider Integration Plan

### Overview

opencode is a CLI-based AI coding assistant that integrates with the AUDiaGentic framework as a provider. This document outlines the repository-aligned integration plan for opencode and matches the canonical `ag-*` prompt surface.

### Provider Classification

| Attribute | Value |
|-----------|-------|
| Provider ID | `opencode` |
| Install Mode | `external-configured` |
| Access Mode | `cli` |
| Prompt Surface Mode | `wrapper-normalize` |
| Execution Classification | `wrapper-first` |

### Architecture Reference

The canonical provider specification lives in `docs/specifications/architecture/providers/09_Opencode.md`.

### Capabilities

| Capability | Supported |
|------------|-----------|
| Jobs | Yes |
| Interactive | Yes |
| Skill Wrapper | No |
| Structured Output | Partial |
| Server Session | No |
| Baseline Healthcheck | Yes |
| Prompt Tag Launch | Yes (via wrapper) |

### Integration Components

#### 1. Provider Adapter (PKT-PRV-064)

**Location:** `src/audiagentic/execution/providers/adapters/opencode.py`

**Responsibilities:**
- Invoke opencode CLI with prompts
- Capture streaming output
- Parse structured responses
- Handle errors gracefully

**Status:** Scaffolded (stub implementation)

#### 2. Prompt-Tag Surface Integration (PKT-PRV-065)

**Configuration:** `.audiagentic/providers.yaml`

```yaml
providers:
  opencode:
    enabled: true
    install-mode: external-configured
    access-mode: cli
    prompt-surface:
      enabled: true
      tag-syntax: prefix-token-v1
      first-line-policy: first-non-empty-line
      cli-mode: wrapper-normalize
      vscode-mode: unsupported
      settings-profile: opencode-prompt-tags-v1
```

**Status:** Documented

#### 3. Tag Execution Implementation (PKT-PRV-066)

**Documentation:** `docs/implementation/providers/19_Opencode_Tag_Execution_Implementation.md`

**Execution Flow:**
```
User prompt with ag-* tag → Wrapper detects tag → Shared bridge → Job creation → opencode adapter execution
```

**Status:** Documented

#### 4. Prompt-Trigger Launch Integration (PKT-PRV-067)

**Bridge:** `tools/opencode_prompt_trigger_bridge.py`

**Usage:**
```bash
python tools/opencode_prompt_trigger_bridge.py --project-root . --surface cli
```

**Status:** Scaffolded

### Installation Requirements

1. opencode CLI installed and available on PATH
2. Verify installation: `opencode --version`

### Configuration

#### Provider Configuration

Add to `.audiagentic/providers.yaml`:

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

### Usage Examples

#### Direct CLI Usage

```bash
# Plan a task
@ag-plan provider=opencode
Plan the implementation of feature X.

# Review code
@ag-review provider=opencode target=artifact:path/to/file.py
Review this implementation.
```

#### Via Bridge

```bash
echo "@ag-plan provider=opencode\nPlan the implementation." | \
    python tools/opencode_prompt_trigger_bridge.py --project-root . --surface cli
```

### Provider Aliases

| Alias | Resolves To |
|-------|-------------|
| `opencode` | `opencode` |
| `opc` | `opencode` |

### Combined Tag-Provider Aliases

| Alias | Resolves To |
|-------|-------------|
| `agp-opc` | `ag-plan provider=opencode` |
| `agi-opc` | `ag-implement provider=opencode` |
| `agr-opc` | `ag-review provider=opencode` |
| `aga-opc` | `ag-audit provider=opencode` |
| `agc-opc` | `ag-check-in-prep provider=opencode` |

### Implementation Status

| Packet | Status |
|--------|--------|
| PKT-PRV-064 (Adapter) | READY_TO_START |
| PKT-PRV-065 (Surface) | READY_TO_START |
| PKT-PRV-066 (Execution) | READY_TO_START |
| PKT-PRV-067 (Trigger) | READY_TO_START |

### Next Steps

1. Implement opencode adapter per PKT-PRV-064
2. Add opencode-specific smoke tests
3. Verify prompt-tag recognition via wrapper
4. Document any opencode-specific limitations or workarounds
