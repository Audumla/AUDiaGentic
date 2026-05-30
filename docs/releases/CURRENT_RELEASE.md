# Current Release

## Changes

### code-fix
- [chg_20260530_023919_logging-rollover] Fixed startup logging errors when another AUDiaGentic process still has diagnostic log open on Windows.

### docs
- [chg_20260530_041900_refactor-cleanup-refs] Cleaned leftover old module references after component naming refactor.

### refactor
- [chg_20260530_025223_lsp-api-refactor] Refactored coding LSP so MCP tools are thin wrappers over internal LSP services.
- [chg_20260530_040800_component-wrapper-refactor] Refactored optional components so module names are explicit and MCP servers stay thin wrappers over internal APIs.
- [chg_20260530_043800_tool-surface-canonicalization] Cleaned MCP tool names and removed confusing public provider config-edit tools.
- [chg_20260530_045400_provider-mcp-ownership] AUDiaGentic now tracks which provider MCP entries it owns, so renames and cleanup do not disturb external entries.
- [chg_20260530_050600_ledger-read-efficiency] Made ledger reads cheaper and manifest handling safer.
- [chg_20260530_051200_ledger-batch-recording] Added batched ledger recording to avoid repeated sync work.
