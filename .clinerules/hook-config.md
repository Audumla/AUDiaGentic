<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

# Cline hook configuration

## Current state

Cline does not expose a native "hook" mechanism for intercepting prompts before the workflow
engine starts. The `.clinerules/` directory provides context and instructions that Cline reads
before each session, but there is no pre-prompt interception hook available in the current
version.

## Fallback-only path

Because native hook interception is not available, this repository uses the **fallback bridge
path exclusively** for Cline prompt-trigger launches:

```powershell
python tools/cline_prompt_trigger_bridge.py --project-root .
```

### How it works

1. User types a tagged prompt (e.g., `@ag-review`) into Cline chat
2. User manually invokes the bridge with the prompt as an argument, OR
3. User copies the tagged prompt and runs the bridge separately

### Bridge invocation examples

```powershell
# Direct invocation with prompt
python tools/cline_prompt_trigger_bridge.py --project-root . --prompt "@ag-review\nReview the current implementation"

# Or pipe a prompt file
Get-Content prompt.txt | python tools/cline_prompt_trigger_bridge.py --project-root .
```

## `.clinerules/` files

While not hooks, the `.clinerules/` files provide important context:

- `.clinerules/prompt-tags.md` — canonical tag doctrine and aliases
- `.clinerules/review-policy.md` — review policy for Cline sessions
- `.clinerules/skills/ag-*.md` — per-tag skill files (generated)

These files are read by Cline before each session and provide the canonical tag semantics,
but they do not intercept or normalize prompts automatically.

## Future considerations

If Cline adds native hook support in a future version, this repository can be updated to:

1. Implement a pre-prompt hook that normalizes the first line
2. Route normalized prompts to the shared launcher
3. Keep the bridge as a fallback for edge cases

Until then, the fallback bridge path is the canonical launch mechanism for Cline.

## Related docs

- `docs/implementation/packets/phase-4/PKT-PRV-037.md`
- `docs/implementation/providers/25_Cline_Prompt_Trigger_Runbook.md`
- `.clinerules/prompt-tags.md`
