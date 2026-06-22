---
id: LSP09
order: 9
plan: unknown
state: draft
wave: W2.5
---

# Server restart/recovery and stale-session invalidation

## Wave 2 — Request lifecycle & resilience

Detect dead/wedged session; allow `get_or_create` to rebuild; invalidate when config changes or command disappears.

**Validate:** Crashed server → new session on next call.

**Depends:** LSP07
**Files:** `lsp_lifecycle.py`, `lsp_session_manager.py`
