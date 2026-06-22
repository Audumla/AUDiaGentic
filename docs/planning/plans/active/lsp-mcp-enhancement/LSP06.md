---
id: LSP06
order: 6
plan: unknown
state: draft
wave: W2.2
---

# Send $/cancelRequest on timeout

## Wave 2 — Request lifecycle & resilience

On `event.wait` expiry, send `$/cancelRequest` with the request id before raising the timeout envelope.

**Validate:** Hung request cancels; later requests still succeed.

**Depends:** LSP05
**Files:** `lsp_bridge.py`
