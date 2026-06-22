---
id: LSP14
order: 14
plan: unknown
state: draft
wave: W4.2
---

# Latency logging for all LSP requests

## Wave 4 — Caching & observability

Wrap `send_request` with timing → `logger.debug` with method + ms.

**Files:** `lsp_bridge.py`
