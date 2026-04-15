---
id: doc-broken-ref-policy
kind: standard
summary: Policy for handling broken references in planning documents
---

# Broken Reference Policy

## Overview

This document defines the policy for handling broken references in planning documents to prevent wasted effort on false positives.

## Policy

### Metadata Fields (YAML Frontmatter)
**Status: MUST FIX**

Broken references in metadata fields (`spec_refs`, `task_refs`, `plan_refs`, `work_package_refs`, etc.) are **actual issues** that must be fixed because they:
- Break automated validation
- Cause tooling failures
- Indicate incomplete or incorrect document relationships

**Action**: Remove or replace with valid references.

### Body Text
**Status: SAFE TO IGNORE**

Broken references in body text (markdown content outside YAML frontmatter) are **historical/documentation** and can be safely ignored because they:
- Provide provenance and context
- Explain the evolution of the planning system
- Do not cause tooling or validation issues
- Are often references to deleted/superseded items

**Action**: Leave as-is. They serve as historical records.

## Examples

### Historical Reference (Safe)
```markdown
# Notes

- `spec-0003` and `wp-0004` capture the earlier archive-workflow framing, 
  while `request-0005` with `spec-0023` and `plan-0009` now carries the 
  cleaner implementation-ready slice.
```
✅ **Keep** - This explains the history and evolution.

### Metadata Reference (Must Fix)
```yaml
---
id: plan-0021
spec_refs:
- spec-0040  # Does not exist
---
```
❌ **Fix** - This breaks validation and tooling.

## Validation Tool

Use `tools/repair_broken_refs.py` to check for broken references:

```bash
# Check metadata only (default - recommended)
python tools/repair_broken_refs.py

# Check including body text (for analysis)
echo "2" | python tools/repair_broken_refs.py
```

The tool by default only checks metadata fields, ignoring body text references.

## Current Status

As of 2026-04-15:
- **Metadata broken refs**: 0 (all fixed)
- **Body text broken refs**: 8 (all historical, safe to ignore)

## Decision Rationale

This policy was established after discovering 107 apparent broken references, of which:
- 99 were false positives (self-references in `id` fields, code block examples)
- 8 were historical body text references
- Only 2 were actual metadata issues (in deleted test artifacts)

The policy prevents wasting time on references that don't cause actual problems.
