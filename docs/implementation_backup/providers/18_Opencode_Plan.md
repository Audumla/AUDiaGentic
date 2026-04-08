# 18_Opencode_Plan.md

## opencode Provider Integration Plan

### Overview

opencode is a CLI-based AI coding assistant that integrates with the AUDiaGentic framework as a provider. This document outlines the repository-aligned integration plan for opencode and matches the canonical `ag-*` prompt surface.

Important architectural rule:
- the repo does not define one shared provider-ready skill format for every provider
- instead, `.audiagentic/skills/` stores the canonical provider-function source
- opencode owns its rendered provider surface under `.opencode/skills/`
- the shared regeneration facade turns the canonical source into provider-specific outputs
- current live prompt-trigger execution still depends on `AGENTS.md` plus
  `.agents/skills/ag-*/SKILL.md` through the wrapper bridge

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
| Provider Function / Skill Surfaces | Yes (via generated provider surfaces) |
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

**Status:** Implemented and test-covered, but still in progress until final adapter hardening and validation land

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

**Status:** In progress; documentation is aligned and `.audiagentic/providers.yaml` now includes the `opencode` entry required for provider-config parity, while adapter hardening and validation still remain

#### 3. Tag Execution Implementation (PKT-PRV-066)

**Documentation:** `docs/implementation/providers/19_Opencode_Tag_Execution_Implementation.md`

**Execution Flow:**
```
User prompt with ag-* tag → Wrapper detects tag → Shared bridge → Job creation → opencode adapter execution
```

**Status:** In progress while adapter/config fixes are still outstanding

#### 4. Prompt-Trigger Launch Integration (PKT-PRV-067)

**Bridge:** `tools/opencode_prompt_trigger_bridge.py`

**Usage:**
```bash
python tools/opencode_prompt_trigger_bridge.py --project-root . --surface cli
```

**Status:** Implemented and test-covered; bridge path is ready for review even though the adapter/config line still needs completion

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
| PKT-PRV-064 (Adapter) | IN_PROGRESS |
| PKT-PRV-065 (Surface) | IN_PROGRESS |
| PKT-PRV-066 (Execution) | IN_PROGRESS |
| PKT-PRV-067 (Trigger) | READY_FOR_REVIEW |

### Next Steps

1. Remove the invalid `--dir` adapter flag and verify the real CLI argument shape against a live `opencode` run
2. Verify the `opencode` entry in `.audiagentic/providers.yaml` stays aligned with the adapter and docs as implementation hardening continues
3. Add adapter tests for non-zero return codes, empty output, and mixed JSON/text output
4. Decide whether opencode should get provider-specific stream milestone extraction beyond the shared sink harness
5. Add structured-completion normalization when Phase 4.11 moves forward for the primary provider set
