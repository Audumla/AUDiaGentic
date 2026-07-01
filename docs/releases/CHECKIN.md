# Check-In Summary

Total changes: 25

- PRR08 complete: Provider recipe lifecycle tests added, foundation/toolchains cleaned of component-specific language, architecture boundary gates all pass, memory/provider separation verified.
- Hindsight memory plan complete (HM01-HM09): Backend config export, remote MCP entry support, strategy contract, TOML writer for openhands, orchestration wiring, boundary gates clean.
- Audit fixes: Matrix provider IDs, TOML writer dispatch for openhands, blocked-row gate, composite MCP+rules recipe, plan state corrections.
- Slimmed MCP tooling config so each component owns its own tool definitions and the agent system prompt no longer carries a duplicated, cross-component tool catalog — reducing context with no loss of tool discoverability (tools are advertised directly over MCP).
- Refactored the Hindsight provider-integration recipes to reuse shared provider-recipe code, cutting ~200 lines of duplicated boilerplate with no behavior change.
- Job and planning state transitions are now defined in per-component workflow config files and validated through shared workflow logic, replacing hardcoded transition tables.
- Configuring a memory backend now automatically installs Hindsight into all enabled providers (and removes it when unconfigured), with per-provider tests validating each provider's files are written and reverted correctly. Also fixed two provisioning bugs that wrote to the wrong location and broke MCP-config providers.
- Hindsight provider installs now run for real when the memory backend is configured — multi-step installer commands execute through the existing toolchain step machinery (pointed at your external server), and providers without a native installer get an MCP config instead.
- Fixed Hindsight MCP provider entries to point at the server's /mcp endpoint instead of the bare base URL, so providers actually connect (verified against a live server).
- Added a Docker test that provisions Hindsight for each provider and validates the files written — including running cline's real installer in isolation — with explicit, reasoned skips for providers that can't be tested yet.
- Fixed Hindsight provider provisioning bugs and merged its Docker e2e coverage into the main provider lifecycle image.
- Updated Hindsight e2e coverage so no individual providers are skipped; each provider is now tested for success or expected failure.
- Adjusted Hindsight provider e2e so the Claude case installs the real Claude CLI before testing integration.
- Tightened Hindsight provider e2e tests to validate exact MCP config shape, managed rule blocks, and installer artifacts instead of generic URL substring checks.
- Fixed the remaining Docker-exposed Hindsight provider install bugs and got the full provider Hindsight lifecycle test passing in Docker.
- Stabilized provider LSP regression coverage by fixing Windows test pollution, restoring OpenHands TOML writer dependency in the LSP Docker harness, and updating e2e expectations to match current Codex and Qwen target state.
- Cleaned and sped up the default regression path, making the main clean Docker suite and provider lifecycle/LSP suites pass again, while narrowing the remaining full-run failures to MCP subprocess harnesses and one provider-cli-comprehensive image build issue.
- Memory (and any configurable component) now reports what configuration it still needs. Running component status on memory shows configured=false with the specific missing option (base-url) and its description, instead of a silent unconfigured state.
- Planning now reports the same standardized configuration status as memory (active implementation, enabled, configured) through component status, using one shared derivation rather than a bespoke per-component rule.
- Configuring memory now only needs a host (port defaults to 8888), reports a clear per-provider integration summary, cleanly skips providers with no Hindsight integration, removes stale integration from disabled providers, and no longer crashes on Windows installer output. Reversal (teardown/prune) is available for every provider.
- Stabilized install and packaging regressions so wheel-based component, MCP, and provider validation now exercise real behavior instead of failing on source-tree assumptions.
- Memory's enabled state now genuinely controls provider integration: disabling uninstalls Hindsight from every provider while keeping your configuration, and re-enabling reinstalls it across providers. Configured and enabled are independent — a configured backend can be switched off and back on without reconfiguring.
- Hindsight now installs and cleanly uninstalls for Claude (and other CLI-driven providers) on Windows. Fixed a crash on installer output with special characters, a Windows path-resolution failure that prevented installers from running at all, and a gap where disabling did not actually remove the Claude plugin.
- Added optional live per-provider tests that validate Hindsight install and teardown against the actual provider CLIs on the developer's machine, in an isolated home so they never modify the real environment. These catch platform-specific install failures and incomplete teardowns that the Docker-only tests miss.
- Fix Claude Code MCP connectivity on Windows: servers were silently broken because pythonw.exe suppresses stdout (now uses python.exe), AUDiaGentic MCP servers now write to ~/.claude/mcp.json (globally available across all projects), and the Hindsight plugin now correctly writes its backend URL to ~/.hindsight/claude-code.json with a Windows repair for the bash→python.exe launcher issue.
