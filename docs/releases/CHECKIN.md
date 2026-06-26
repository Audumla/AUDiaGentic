# Check-In Summary

Total changes: 19

- Fixed GitHub authentication for release dispatch: device-flow OAuth now works as a non-blocking start/poll pair over MCP, with GITHUB_TOKEN environment-variable support as an immediate alternative.
- LSP tools now auto-install missing language servers from their YAML recipes when a file is opened
- Added Agent Profiles component: manage provider+model bindings per-project, resolve profiles at job launch, with MCP tools for CRUD and resolution. Agent jobs now support agent-profile-id directive with automatic provider enablement checks.
- Fixed stale MCP and language-server processes piling up after the agent host exits or is killed — child processes are now reliably terminated with their parent on all platforms.
- MCP servers now launch without flashing console windows and with fewer background processes each, and every provider config — even ones you're not currently using — is kept in sync.
- Tests now run from one command (`make test-all` / `tests/run_all.py`): the full non-Docker suite executes in parallel, and Docker suites run automatically when a daemon is present. Docker images were consolidated where safe (faster, parallel CI), while the recipe install/uninstall tests stay isolated so they keep genuinely testing dependency installation.
- Running `python tests/run_all.py` on Windows now delegates everything to Docker when a daemon is present - no duplicate test passes. If no Docker daemon, falls back to the Windows-safe non-mutating suite.
- Unified the test suite so a single command (`python tests/run_all.py`) runs everything — when Docker is present it handles all phases; without Docker it runs the parallel host suite. Fixed 9 failures found by the first full consolidated run, covering provider descriptor metadata, LSP config key naming, Docker assertion format, and two Docker image build failures.
- Fixed ag-lsp workspace diagnostics on Windows by launching batch diagnostic CLIs through a Windows-safe wrapper, preventing WinError 2.
- Made ag-lsp skip broken or missing language servers instead of failing the whole request.
- Expanded test coverage so every declared Python MCP server is smoke-tested automatically, and added a small host-side smoke phase to catch local Windows PATH/CLI breakage that Docker cannot see.
- Fixed the broken coding-lsp status hook and hardened CLI probe decoding so MCP smoke no longer throws Unicode decode crashes.
- Added JSON, TOML, and Makefile language support to coding-lsp, including proper Makefile basename matching and unit coverage.
- Docker test infrastructure now includes Go toolchain and validates make-ls auto-install in a blank container environment.
- Makefile LSP dependency now uses the structured go toolchain pattern instead of platform-specific fallback commands.
- Added memory component — persistent memory for agent sessions with swappable backends. Hindsight is the default implementation. Memory config projects into provider surfaces with per-provider integration modes.
- Fixed memory component architecture — removed provider-specific logic. Memory now contributes generic content through the existing surface contribution system; providers handle rendering.
- Added a reusable provisioning-recipe foundation so provider integrations (memory/Hindsight, LSP) can install, configure, verify, and cleanly uninstall host tooling through shared, safe primitives.
- Memory (Hindsight) and LSP now have full install/verify/uninstall recipes on the shared provisioning model, plus a verified harness integration matrix mapping each supported tool to its install strategy.
