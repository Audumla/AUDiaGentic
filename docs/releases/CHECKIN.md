# Check-In Summary

Total changes: 14

- Fixed startup logging errors when another AUDiaGentic process still has diagnostic log open on Windows.
- Refactored coding LSP so MCP tools are thin wrappers over internal LSP services.
- Refactored optional components so module names are explicit and MCP servers stay thin wrappers over internal APIs.
- Cleaned leftover old module references after component naming refactor.
- Cleaned MCP tool names and removed confusing public provider config-edit tools.
- AUDiaGentic now tracks which provider MCP entries it owns, so renames and cleanup do not disturb external entries.
- Made ledger reads cheaper and manifest handling safer.
- Added batched ledger recording to avoid repeated sync work.
- Made fragments the sole source of truth for current release ledger sync.
- Toolchain declarations consolidated from 12 Python files into a single YAML-driven loader. Foundation layout cleaned up.
- Dependency declarations moved out of hardcoded Python into component YAML files. Install/uninstall logic now expressed as workflow steps, eliminating a separate dependency management lane.
- Added SelectStep workflow primitive for N-variant runtime dispatch. Layer boundaries enforced: toolchains/ never imported from dependency layer. Probe-guard pattern extracted to shared helper.
- Provider descriptors no longer import foundation toolchains directly. Install specs are now declared via cli_recipe() which builds steps through the toolchain loader.
- Fixed provider CLI plan crash and state machine protocol mismatch. All pre-existing provider and provisioning test failures resolved.
