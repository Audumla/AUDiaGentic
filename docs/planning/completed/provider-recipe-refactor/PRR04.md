---
id: PRR04
order: 4
plan: plan-provider-recipe-refactor
state: completed
validate-first: true
priority: P0
work: M
---

# Build source-backed Hindsight provider recipe matrix

## Description

Create the authoritative Hindsight integration recipe matrix for AUDiaGentic providers from official Hindsight docs. This is the source of truth for which provider recipe each adapter should register.

## Steps

1. For each AUDiaGentic provider with relevant official Hindsight support, capture source URL, integration type, install command, uninstall command, status command/probe, config artifacts, platform limits, and whether setup is project-local or global.
2. Include at minimum: `codex` hooks installer, `claude` plugin marketplace install, `cline` hook installer, `copilot` MCP+instructions CLI, `opencode` plugin config, `openhands` MCP+AGENTS rule CLI, `roo` MCP+rules CLI, `continue` context-provider plus optional MCP/rules, `aider` wrapper CLI, `gemini` Spark MCP config if applicable to our `gemini` adapter, and unsupported/no-source providers.
3. For each row, decide whether AUDiaGentic should call official installer command directly, reproduce managed config writes itself, or present action-needed guidance.
4. Mark platform constraints explicitly, especially Cline hooks being macOS/Linux only in official docs.
5. Compare official artifacts against existing provider descriptor capabilities (`mcp_config`, surfaces, hooks, plugins, CLI install recipe) and list missing provider tooling.
6. Store matrix in plan item notes or a dedicated docs file referenced by this plan.

## Files

docs/planning/active/provider-recipe-refactor/PRR04.md or referenced matrix doc
src/audiagentic/components/providers/adapters/*/README.md if docs are colocated later

## Validation

- Each matrix row has an official source URL and date checked.
- Each official installer/status/uninstall command is captured verbatim enough for implementation.
- No implementation work starts for a provider without a matrix row.
- Unsupported providers are explicit, not inferred.

## Effort & Risk

Risk is stale or incomplete docs causing bad recipes. Mitigation: use official Hindsight integration pages as primary sources and record no-source providers separately.

## Notes

Confirmed examples: Codex uses hook scripts via `get-codex`; Claude Code uses `claude plugin marketplace add` + `claude plugin install`; Cline uses `pip install hindsight-cline` + `hindsight-cline install/uninstall`; Copilot uses `hindsight-copilot init/status/uninstall`; OpenCode uses plugin array; OpenHands/Roo/Windsurf use MCP config plus rule installers; Aider uses wrapper CLI; Continue uses context provider plus optional MCP/rules.
