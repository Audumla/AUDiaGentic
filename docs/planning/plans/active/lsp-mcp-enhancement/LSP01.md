---
id: LSP01
order: 1
plan: plan-lsp-mcp-enhancement
state: draft
wave: W0.1
---

# Reader-loop notification dispatch

## Wave 0 — Reader-loop message demux

The reader loop only routes responses; notifications and server→client requests are dropped.

**Steps:** In `_reader_loop`, branch on message shape — `id` present + in `_pending` → response; `method` present + no `id` → notification → invoke registered callback map. Add `on_notification(method, handler)` registration.

**Validate:** Fake server emits `textDocument/publishDiagnostics`; handler fires.

**Files:** `lsp_bridge.py`
