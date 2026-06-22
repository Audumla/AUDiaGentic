---
id: LSP05
order: 5
plan: plan-lsp-mcp-enhancement
state: draft
wave: W2.1
phase: Phase 0
---

# Per-request and method-specific timeouts

## Context

Wave W2.1 — Request lifecycle & resilience.

## Steps

Replace the single 30s default with a method→timeout map and per-call override.

**Performance budgets:**
| Operation class | Target | Hard timeout |
|---|---:|---:|
| File diagnostics | <= 1.5s typical | 5s |
| Hover/definition/references | <= 750ms typical | 3s |
| Workspace symbols | <= 2s typical | 8s |
| Workspace diagnostics | explicit only | 30s |
| Server initialize | <= 5s typical | 30s |

## Files

`lsp_bridge.py`

## Validation

Validate against performance-budget table above.

## Dependencies

LSP04 (timeout → envelope)

## Notes


