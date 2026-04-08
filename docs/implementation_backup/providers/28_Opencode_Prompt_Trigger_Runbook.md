# opencode Prompt Trigger Runbook

## Overview

This runbook describes how to set up and use prompt-trigger launch with opencode in the AUDiaGentic framework.

## Prerequisites

1. opencode CLI installed and available on PATH
2. AUDiaGentic project initialized
3. PKT-PRV-064 in progress or better (opencode adapter implemented, but still under validation)

## Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   User       │────▶│ opencode Wrapper │────▶│ Shared Bridge   │
│   Prompt     │     │ (tag detection)  │     │ (normalization) │
└──────────────┘     └──────────────────┘     └────────┬────────┘
                                                       │
                                                       ▼
                                              ┌─────────────────┐
                                              │ Job Creation    │
                                              │ & Execution     │
                                              └─────────────────┘
```

## Setup Steps

### Step 1: Verify opencode Installation

```bash
opencode --version
```

Expected: Version information displayed

### Step 2: Configure Provider

Add to `.audiagentic/providers.yaml`:

```yaml
providers:
  opencode:
    enabled: true
    install-mode: external-configured
    access-mode: cli
    default-model: <your-model>
    timeout-seconds: 120
    prompt-surface:
      enabled: true
      tag-syntax: prefix-token-v1
      first-line-policy: first-non-empty-line
      cli-mode: wrapper-normalize
      vscode-mode: unsupported
      settings-profile: opencode-prompt-tags-v1
```

Current repository note:
- this config block now exists in the live `.audiagentic/providers.yaml`
- remaining work is adapter hardening and end-to-end validation, not provider-config parity

### Step 3: Verify Bridge Availability

```bash
ls -la tools/opencode_prompt_trigger_bridge.py
```

Expected: File exists and is executable

## Usage

opencode uses the shared bridge for launch. The current live wrapper path still validates
`AGENTS.md` plus `.agents/skills/ag-*/SKILL.md`.

Separately, the provider-owned generated opencode surface now lives under
`.opencode/skills/ag-*/SKILL.md`. That surface is generated from the canonical
provider-function source under `.audiagentic/skills/`; it is not a shared generic skill file
format reused directly across providers, and it is not yet the active wrapper dependency.

### Basic Usage

```bash
echo "@ag-plan provider=opencode\nPlan the implementation." | \
    python tools/opencode_prompt_trigger_bridge.py --project-root . --surface cli
```

### Using Provider Alias

```bash
echo "@ag-plan provider=opc\nPlan the implementation." | \
    python tools/opencode_prompt_trigger_bridge.py --project-root . --surface cli
```

### Using Combined Alias

```bash
echo "@agp-opc\nPlan the implementation." | \
    python tools/opencode_prompt_trigger_bridge.py --project-root . --surface cli
```

### Review Example

```bash
echo "@ag-review provider=opencode target=artifact:src/main.py\nReview this code." | \
    python tools/opencode_prompt_trigger_bridge.py --project-root . --surface cli
```

## Verification

### Check Job Creation

After running a tagged prompt, verify job was created:

```bash
ls -la .audiagentic/runtime/jobs/
```

### Check Job Record

```bash
cat .audiagentic/runtime/jobs/<job-id>/job-record.json | jq
```

Expected fields:
- `tag`: Should be canonical tag (e.g., `ag-plan`)
- `provider-id`: Should be `opencode`
- `target`: Should match the target specified

## Troubleshooting

### Issue: "opencode command not found"

**Cause:** opencode CLI not installed or not on PATH

**Solution:**
```bash
# Install opencode (check official documentation for installation)
# Then verify:
opencode --version
```

### Issue: "unknown prompt tag"

**Cause:** Tag not recognized or malformed

**Solution:**
- Ensure tag is on first non-empty line
- Use valid canonical tags: `@ag-plan`, `@ag-implement`, `@ag-review`, `@ag-audit`, `@ag-check-in-prep`
- Check for typos in tag name

### Issue: "provider is required"

**Cause:** No provider specified and no default configured

**Solution:**
- Add `provider=opencode` to prompt
- Or use combined alias like `@agp-opc`

### Issue: Bridge returns validation error

**Cause:** Prompt syntax error or missing required fields

**Solution:**
- Check prompt format
- Ensure all required directives are present
- Review error details in bridge output

## Advanced Usage

### Custom Stream Controls

```bash
echo "@ag-plan provider=opencode\nPlan the implementation." | \
    python tools/opencode_prompt_trigger_bridge.py \
        --project-root . \
        --surface cli \
        --stream-controls-json '{"enabled": true, "tee-console": true}'
```

### Custom Workflow Profile

```bash
echo "@ag-plan provider=opencode\nPlan the implementation." | \
    python tools/opencode_prompt_trigger_bridge.py \
        --project-root . \
        --surface cli \
        --workflow-profile custom-profile
```

## Optional: CLI Wrapper Script

For seamless integration, create a wrapper script:

```bash
#!/bin/bash
# ~/.local/bin/opencode-wrapper

OPENCODE_BIN="opencode"
BRIDGE="$(pwd)/tools/opencode_prompt_trigger_bridge.py"

# Read first line from stdin or first argument
if [ -n "$1" ]; then
    FIRST_LINE="$1"
else
    FIRST_LINE=$(head -n1)
fi

# Check if first line starts with @
if [[ "$FIRST_LINE" == @* ]]; then
    # Route through bridge
    exec python "$BRIDGE" --project-root "$(pwd)" --surface cli
else
    # Pass through to opencode
    exec "$OPENCODE_BIN" "$@"
fi
```

Make executable:

```bash
chmod +x ~/.local/bin/opencode-wrapper
```

## Rollback

To disable prompt-trigger launch:

1. Set `prompt-surface.enabled: false` in provider config
2. Remove wrapper script from PATH (if installed)
3. Revert any custom bridge configurations

## Related Documents

- [PKT-PRV-067](../../implementation/packets/phase-4/PKT-PRV-067.md) - opencode prompt-trigger launch integration
- [18_Opencode_Plan.md](18_Opencode_Plan.md) - opencode provider integration plan
- [19_Opencode_Tag_Execution_Implementation.md](19_Opencode_Tag_Execution_Implementation.md) - opencode tag execution implementation
