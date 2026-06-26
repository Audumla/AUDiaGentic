# Harness Integration Matrix (TO09)

Discovery artifact for the provisioning-recipe model. Classifies each supported
harness by the integration **strategy** Hindsight (and similar capabilities) use,
and maps each to the recipe primitives delivered in TO01–TO06 and the recipes in
TO07–TO08.

## Confidence legend

- **descriptor-verified** — config path/format taken directly from the provider
  adapter `McpConfigSpec` in this repo (authoritative for *where* an entry goes).
- **strategy-inferred** — integration strategy derived from harness architecture;
  the Hindsight-specific official install steps still need source confirmation.
- **source-needed** — official Hindsight integration page not yet re-verified in
  this pass; flagged before any live cut-over.

## Strategy taxonomy

| Strategy | Mechanism | Recipe primitive |
|---|---|---|
| `mcp-config` | write MCP server entry into harness config | provider `McpConfigSpec.writer` (preferred) or `ConfigPatcher.add_mcp_entry` (generic fallback) |
| `hooks` | register a hook/command block | `managed_block` apply/remove + `ConfigPatcher` |
| `plugin` | install a plugin/package | `StepRecipe` over a toolchain install step |
| `command-installer` | run an official installer (`curl … | bash`) | `StepRecipe` over a `ShellStep` (with `PlatformOverrides`) |
| `rules-only` | descriptive guidance in instruction files (no install) | existing surface contribution (fallback) |
| `native-built-in` | harness ships the capability | no recipe needed |

## Provider matrix

MCP config destinations are **descriptor-verified** from each adapter's
`McpConfigSpec.config_path`. The Hindsight strategy column is **strategy-inferred /
source-needed** — confirm against the official integration page before cut-over.

| Provider | MCP config path | Format | Primary strategy | Notes |
|---|---|---|---|---|
| claude | `.mcp.json` | JSON | mcp-config | `mcpServers` container |
| cline | `.mcp.json` | JSON | mcp-config | shares `.mcp.json` |
| codex | `.codex/config.toml` | **TOML** | mcp-config | **needs `tomli-w`** for generic write; provider writer already handles TOML |
| continue_ | `.continue/config.json` | JSON | mcp-config | |
| copilot | `.mcp.json` | JSON | mcp-config (+ instructions) | VS Code may also read `.vscode/mcp.json` — verify |
| gemini | `.gemini/settings.json` | JSON | mcp-config | entry nested under settings — confirm container key |
| goose | `.goose/config.yaml` | **YAML** | mcp-config | extension/`extensions` container — verify |
| opencode | `.opencode/opencode.json` | JSON | mcp-config / plugin | OpenCode also supports plugins; confirm preferred path |
| local_openai | — (`mcp_config=None`) | — | rules-only | no MCP support; fallback contribution only |
| aider | source-needed | — | strategy-inferred | confirm MCP support + path |
| openhands | source-needed | — | strategy-inferred | sandboxed; may need in-container install |
| pi / plandex / qwen / roo | source-needed | — | strategy-inferred | confirm adapter `McpConfigSpec` presence |

## Key architectural conclusions

1. **Providers already own MCP config format.** Each `McpConfigSpec` carries its
   own `reader/writer/remover`. For the `mcp-config` strategy the Hindsight recipe
   should **delegate to the provider writer** (handles TOML/JSON/YAML + container
   key correctly), reserving the generic `ConfigPatcher` path for harnesses
   without an adapter writer and for the non-MCP strategies (hooks/plugin/installer).
   `HindsightMcpRecipe` demonstrates the generic path and accepts an
   `entry_builder` + `HindsightTarget` override so a provider-writer-backed variant
   slots in without changing the contract.

2. **The recipe model's net-new value is lifecycle + non-MCP strategies.** Existing
   machinery writes MCP entries but has no probe/verify/uninstall/prune lifecycle
   and no hooks/plugin/installer support. TO01–TO06 supply exactly those.

3. **LSP is already recipe-shaped.** Language-server installs run through the
   probe-guarded dependency workflow; `lsp_language_recipe` wraps it via
   `StepRecipe` with zero behavior change (TO07).

## Open verification items (gate before live cut-over)

- [ ] Re-fetch official Hindsight integration page per harness; confirm strategy.
- [ ] Confirm `gemini` / `goose` MCP container key paths.
- [ ] Confirm `copilot` `.vscode/mcp.json` vs `.mcp.json` precedence.
- [ ] Confirm MCP support + paths for aider, openhands, pi, plandex, qwen, roo.
- [ ] Add `tomli-w` dependency before enabling the generic TOML write path (codex).
