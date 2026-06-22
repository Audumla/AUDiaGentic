---
id: LSP07
order: 7
plan: unknown
state: draft
wave: W2.3
---

# In-flight tracking and clean fail on server exit

## Wave 2 — Request lifecycle & resilience

On `_process` exit, fail all `_pending` with a crashed-server envelope.

**Validate:** Kill server mid-request → caller gets envelope, not a hang.

**Depends:** LSP04
**Files:** `lsp_bridge.py`
