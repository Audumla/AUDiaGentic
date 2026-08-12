# Provider Config Override Analysis

Status: investigation — pre-work for provider capability documentation
Last checked: 2026-07-16

## Scope

Can each provider be started with a **completely different config location** — i.e., override the default project or global config file, specifying an alternate path for MCP servers, models, LSP, and other settings at startup?

This determines whether AUDiaGentic can launch a provider in isolation without mutating the user's existing config files.

## Terminology

| Term | Meaning |
|---|---|
| **CLI flag** | A command-line argument (e.g., `--config`, `-c`) that accepts a file path. |
| **Env var** | An environment variable that overrides the config file location. |
| **Inline config** | Passing config content directly via CLI arg or env var, bypassing a file. |
| **Scoped config** | The product supports separate project/user/global config files with precedence.

## Provider config override matrix

| Provider | CLI flag | Env var | Inline config | Scope | Notes |
|---|---:|---:|---:|---|---|
| OpenCode | No (no `--config` flag) | `OPENCODE_CONFIG` — file path | `OPENCODE_CONFIG_CONTENT` — inline JSON | Project + global | Also `OPENCODE_CONFIG_DIR` for config directory, `OPENCODE_TUI_CONFIG` for TUI-specific config. Most flexible in our scope. |
| Kilo Code | No (no `--config` flag) | `KILO_CONFIG` — file path (inherited from OpenCode) | `KILO_CONFIG_CONTENT` — inline JSON | Project + global | Fork of OpenCode; same env var convention applies. |
| Qwen Code | `--settings <path>` | No documented env var | No | Project `.qwen/settings.json` + user `~/.qwen/settings.json` | CLI flag overrides the default settings file location. |
| Codex CLI | `-c <path>` / `--config-dir <path>` | No | No | Trusted project `.codex/config.toml` + user `~/.codex/config.toml` | The `-c` flag can override `[model_providers]` keys in the config file. Profiles via separate `~/.codex/profile-name.config.toml` files (v0.134+). |
| Claude Code | No | No | No | User `~/.claude/settings.json` + project `.claude/settings.json` | Config location is fixed. Project-local cannot override all fields (auth, model_providers are user-only). |
| Gemini CLI | No documented flag | No | No | Fixed user config location | Subscription login uses `~/.gemini/oauth_creds.json`. |
| Cline | No (VS Code extension) | No | No | Extension storage / IDE settings | Configured via VS Code UI or CLI auth commands. Not a standalone CLI with overrideable config path. |
| GitHub Copilot | No | No | No | Fixed user account config | Account-derived; no project-level generic config override. |
| Pi | No documented flag | No | No | User `~/.pi/agent/models.json` | Config location is fixed at user home. |
| OpenHands | No (V1 UI-driven) | V0: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`; V1: env vars for SDK | No | V0: `.openhands/config.toml`; V1: UI/SDK/env | Current V1 is primarily UI/env/SDK. Agent Canvas uses environment variables, not config files. |
| Crush | No documented flag | No | No | Project + global JSON | Config location appears fixed at default paths. |
| Continue | `--config-dir <path>` (CLI) | No | No | User/project depending on installed version | Current versions use YAML; legacy JSON deprecated. |
| Goose | `--config <path>` (CLI) | No documented env var | No | User config + launch-time overrides | Also supports launch-time provider/model/base URL/key environment mechanisms. |
| Aider | `--config <path>` / `-c <path>` | No | No | User/project `.aider.conf.yml` | Well-documented config override support. |

## Key findings

### Tier 1: Full config isolation (can start with completely separate config)

These providers allow starting with an entirely different config file, enabling AUDiaGentic to launch in isolation:

| Provider | Mechanism | What it covers |
|---|---|---|
| OpenCode | `OPENCODE_CONFIG` + `OPENCODE_CONFIG_CONTENT` | All: MCP, LSP, models, providers, permissions |
| Kilo Code | `KILO_CONFIG` + `KILO_CONFIG_CONTENT` | Same as OpenCode |
| Qwen Code | `--settings <path>` | Providers, models, all settings |
| Codex CLI | `-c <path>` | Model providers, base URL (but project-local cannot override some keys like `model_providers`, `openai_base_url`) |

### Tier 2: Partial config isolation

These providers allow some config override but with restrictions:

| Provider | What can be overridden | What cannot |
|---|---|---|
| Continue | Config directory path via `--config-dir` | User-scoped fields may remain in default location |
| Goose | Config file via `--config`; launch env for provider/model/key | Some settings may still read from user config |
| Aider | Config file via `-c` / `--config` | Some settings may remain fixed |

### Tier 3: No config isolation

These providers **cannot** be started with a different config location. Any integration must work within the existing config or use launch-time environment variables only:

| Provider | Workaround |
|---|---|
| Claude Code | None — fixed config paths |
| Gemini CLI | None — fixed config paths |
| Cline | None — VS Code extension storage |
| GitHub Copilot | None — account-derived |
| Pi | None — fixed user home path |
| OpenHands V1 | Environment variables only (LLM_API_KEY, LLM_BASE_URL, LLM_MODEL) |
| Crush | None documented |

### The inline config advantage

Only OpenCode and Kilo Code support `OPENCODE_CONFIG_CONTENT` / `KILO_CONFIG_CONTENT` — passing the entire config as a string via environment variable. This is the strongest isolation mechanism because:

1. No file I/O is needed — the provider reads from memory.
2. The user's actual config files are never touched.
3. AUDiaGentic can render the exact config it wants at launch time.
4. Multiple concurrent providers with different configs can run simultaneously.

## Implications for AUDiaGentic

### AUDiaGentic-owned provider settings files

Each provider has one complete project-owned settings document:

```text
.audiagentic/config/providers/<provider-id>.yaml
```

The file contains shared launch fields and an optional provider-owned
`settings` mapping:

```yaml
install-mode: external-configured
access-mode: none
settings:
  browser_port: 9224
```

The providers component discovers these files and passes the merged provider
mapping to execution. The reconciliation policy is stored separately in
`.audiagentic/config/provider-policy.yaml`; there is no shared provider
registry file. Provider adapters explicitly consume their `settings` keys.

- **OpenCode and Kilo Code** provide the best isolation story: `OPENCODE_CONFIG_CONTENT` / `KILO_CONFIG_CONTENT` allows AUDiaGentic to launch a provider instance with a completely independent config without any filesystem interaction.
- **Qwen Code**'s `--settings <path>` is useful for project-level isolation but requires writing to disk.
- **Codex**'s `-c` flag is limited: even when pointing to a different file, `model_providers` cannot be overridden in project-local config — custom providers must live in the user-level config.
- For providers in **Tier 3**, AUDiaGentic must either:
  - Use launch-time environment variables only (where available), OR
  - Write to the provider's fixed config file with reconciliation, OR
  - Avoid integration with that provider.
- The `OPENCODE_CONFIG_CONTENT` pattern is worth proposing for other providers — it solves the multi-project isolation problem cleanly.
