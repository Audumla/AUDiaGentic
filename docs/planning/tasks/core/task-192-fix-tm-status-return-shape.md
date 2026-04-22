---
id: task-192
label: Fix tm.status() return shape
state: done
summary: Align tm.status() return keys with {request, spec, plan, task, wp} naming
spec_ref: spec-6
---








# Description

Normalize `tm.status()` so callers receive stable kind counts with the expected `{request, spec, plan, task, wp}` keys.

# Acceptance Criteria

1. Status payload contains the expected kind keys
2. Key names are stable across helper and MCP usage
3. Regression coverage proves the expected shape

# Notes

- Verified by status assertions in the MCP and planning coverage tests
