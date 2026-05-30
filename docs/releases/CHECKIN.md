# Check-In Summary

Total changes: 9

- Fixed startup logging errors when another AUDiaGentic process still has diagnostic log open on Windows.
- Refactored coding LSP so MCP tools are thin wrappers over internal LSP services.
- Refactored optional components so module names are explicit and MCP servers stay thin wrappers over internal APIs.
- Cleaned leftover old module references after component naming refactor.
- Cleaned MCP tool names and removed confusing public provider config-edit tools.
- AUDiaGentic now tracks which provider MCP entries it owns, so renames and cleanup do not disturb external entries.
- Made ledger reads cheaper and manifest handling safer.
- Added batched ledger recording to avoid repeated sync work.
- Made fragments the sole source of truth for current release ledger sync.
