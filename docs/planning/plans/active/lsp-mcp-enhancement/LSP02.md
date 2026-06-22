---
id: LSP02
order: 2
plan: unknown
state: draft
wave: W0.2
---

# Server→client request handling

## Wave 0 — Reader-loop message demux

**Steps:** `method` present + `id` present → inbound request. Reply to `workspace/configuration` (null/defaults) and `client/registerCapability` (ack/empty result). Default-reply null + log for unknown server requests.

**Validate:** Fake server issues `workspace/configuration`; bridge replies; server unblocks.

**Depends:** LSP01
**Files:** `lsp_bridge.py`
