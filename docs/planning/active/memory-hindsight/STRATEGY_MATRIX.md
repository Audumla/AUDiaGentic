# Hindsight Per-Provider Strategy Matrix (HM08)

Authoritative mapping of every AUDiaGentic provider to its Hindsight integration
strategy — what we **can** do and what we **cannot** (yet). This matrix is the
planning source of truth, but entries are executable only when their source
status is `verified` with exact official evidence from `hindsight.vectorize.io`
or inspected installer source. Live test server: `http://10.10.100.10:8888/mcp`.

## Strategy kinds

- **native-installer** — run Hindsight's official per-harness installer/plugin non-interactively; we supply the connection config (HM04).
- **launch-wrapper** — Hindsight replaces the harness launch command (aider only).
- **mcp-config + rule** — write remote MCP entry via the provider's own writer + a managed recall/retain rule block (HM05).
- **fallback-mcp** — generic remote MCP entry for MCP-capable harnesses Hindsight does not officially support (works as a plain MCP client; recall/retain rule supplied by us).
- **rules-only** — instruction text only; no MCP, no native (HM06).

## Matrix

| Provider | Hindsight official? | Native mechanism | Our `mcp_config` | Strategy we ship | Source status |
|---|---|---|---|---|---|
| **claude** | ✅ | plugin/hooks | `.mcp.json` | native-installer | unconfirmed until exact official commands + uninstall captured |
| **codex** | ✅ | installer `get-codex` (hooks) | `.codex/config.toml` | native-installer | partial: official URL known; exact flags/config/probes need capture |
| **opencode** | ✅ | plugin | `.opencode/opencode.json` | native-installer (plugin) | unconfirmed until exact official install/uninstall captured |
| **cline** | ✅ | lifecycle hooks, no MCP | `.mcp.json` (unused for HS) | native-installer | unconfirmed; macOS/Linux only must be verified |
| **aider** | ✅ | launch wrapper | none | launch-wrapper | unconfirmed until package/binary/config/uninstall captured |
| **copilot** | ✅ | MCP + rule | `.mcp.json` | mcp-config + rule | unconfirmed path mismatch: `.vscode/mcp.json` vs `.mcp.json` |
| **openhands** | ✅ | MCP into `config.toml` + rule | **none** | mcp-config + rule | blocked: adapter has no `mcp_config` |
| **continue_** | ✅ | MCP client + optional auto recall/retain | `.continue/config.json` | mcp-config (+ rule) | unconfirmed until exact official config path/rule captured |
| **roo** | ✅ | MCP client | `.mcp.json` | mcp-config (+ rule) | unconfirmed until exact official config path/rule captured |
| **gemini** | ✅ | MCP client (OAuth proxy for Cloud) | `.gemini/settings.json` | mcp-config | partial: self-hosted direct likely; Cloud OAuth proxy separate |
| **goose** | ❌ not listed | — | `.goose/config.yaml` | fallback-mcp | MCP-capable; our rule, no official hooks |
| **pi** | ❌ not listed | — | `.mcp.json` | fallback-mcp | unverified harness |
| **qwen** | ❌ not listed | — | `.mcp.json` | fallback-mcp | not in official list |
| **plandex** | ❌ not listed | — | **none** | rules-only | **cannot do MCP** |
| **local_openai** | ❌ (no MCP) | — | **none** (`mcp_config=None`) | rules-only | **cannot do MCP** |

## What we CANNOT do (gaps & limitations)

1. **openhands — blocked.** Hindsight officially supports it (MCP entry into `config.toml` + rule), but our `openhands` adapter declares **no `mcp_config`**. We cannot write its MCP config until the adapter gains an `McpConfigSpec` (TOML writer for `config.toml`). → adapter prerequisite.
2. **aider — needs launch interception, not config.** Native Hindsight for aider is a **command wrapper** (`hindsight-aider`) that replaces the `aider` invocation and writes `.aider.hindsight-memory.md`. To use it, AUDiaGentic must launch `hindsight-aider` instead of `aider` — a provider-launch change, not a file write. No `mcp_config` exists, so there is **no MCP fallback**. → new launch-wrapper strategy + launch-command override.
3. **cline — Windows unsupported.** `hindsight-cline` hooks run on **macOS/Linux only**. On a Windows host (current dev environment) cline native cannot be installed; it has no MCP path either (hooks-only), so Windows → rules-only at best.
4. **plandex, local_openai — no MCP, no native.** Only rules-only guidance is possible.
5. **copilot path mismatch.** Our adapter writes `.mcp.json`; Hindsight's Copilot method targets `.vscode/mcp.json` + `.github/copilot-instructions.md`. Confirm which path the running Copilot actually reads before shipping.
6. **Platform gating generally.** Native installers that rely on POSIX shell / `python3` hooks (codex, cline) must be platform-guarded; on unsupported hosts fall back to mcp-config (where available) or rules-only.

## What we CAN do cleanly

- **Full native lifecycle:** only after HM08/HM04 source audit verifies exact official commands and uninstall behavior.
- **MCP-config + rule:** copilot (pending path confirm), continue_, roo, gemini (self-hosted) after config path/rule source capture.
- **Generic MCP fallback:** goose, pi, qwen.
- **Rules-only:** plandex, local_openai (and any provider on an unsupported platform).

## Connection-config seams (per native integration)

- codex → `~/.hindsight/codex.json` `{hindsightApiUrl, hindsightApiToken}` or `HINDSIGHT_*` env.
- opencode → `HINDSIGHT_API_URL` / `HINDSIGHT_API_TOKEN` env or `~/.hindsight/opencode.json`.
- cline → `hindsight-cline install --api-url --api-token` or `~/.hindsight/cline.json`.
- aider → `HINDSIGHT_API_TOKEN` env (+ pip install).
- claude → `~/.hindsight/claude-code.json`.

These seams are candidate targets until source status is verified. Do not turn them
into executable HindsightSpec commands without exact official evidence.
