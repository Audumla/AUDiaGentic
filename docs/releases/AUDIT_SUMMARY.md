# Audit Summary

Total events: 9

- chg_20260530_023919_logging-rollover: Added safe timed log rotation fallback for Windows locked-file rollover and covered it with regression tests.
- chg_20260530_025223_lsp-api-refactor: Extracted shared LSP orchestration into lsp_api, made MCP modules thin delegates, moved diagnostics behind SessionManager API, and added regression tests for root/language resolution.
- chg_20260530_040800_component-wrapper-refactor: Renamed generic optional-component root modules to component-prefixed names, extracted provider and source-control internal APIs, made MCP wrappers delegate to *_api modules, and added guardrail tests for naming and same-component MCP imports.
- chg_20260530_041900_refactor-cleanup-refs: Removed stale module-path and entrypoint references left by component renames, including legacy ledger bootstrap metadata and outdated knowledge README commands.
- chg_20260530_043800_tool-surface-canonicalization: Canonicalized MCP tool naming by removing project _tool suffixes, consolidating release status onto get_release_status, renaming provider_status to get_provider_status, and pruning public provider tools that directly edit provider MCP config or bypass managed reconciliation.
- chg_20260530_045400_provider-mcp-ownership: Validated that embedded ownership metadata was not safely provable across all provider config formats, then implemented a small managed MCP registry keyed by stable managed_id so AUDiaGentic can rename or remove only its own provider MCP entries while preserving external entries.
- chg_20260530_050600_ledger-read-efficiency: Made ledger summary reads reuse existing CURRENT_RELEASE.md instead of regenerating on every read, added explicit refresh_current_summary and optional record_change(sync=False), and made manifest writes atomic with tolerant status reads.
- chg_20260530_051200_ledger-batch-recording: Added record_changes(...) to batch multiple fragment writes and optionally sync once at the end, with tests proving deferred sync leaves the current ledger untouched until final merge.
- chg_20260530_052000_ledger-fragments-source-of-truth: Made current release ledger rebuild from fragments only, so CURRENT_RELEASE_LEDGER.ndjson is treated as generated output and stale/manual entries are discarded on sync.
