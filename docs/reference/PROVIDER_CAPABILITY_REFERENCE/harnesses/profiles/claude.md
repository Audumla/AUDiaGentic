# Claude Code Provider — P1 Vendor Verification Evidence

<a name="claude-evidence"></a>

## Record header

| Field | Value |
|---|---|
| provider-id | `claude` |
| upstream-id | Anthropic/claude-code |
| tool-version | 2.1.199; upstream docs revalidated 2026-07-16 |
| verified-at | 2026-07-13 UTC, 2026-07-16 UTC (upstream doc revalidation) |
| evidence-kind | installed-tool CLI probe (`claude --help`, `--version`), settings file inspection (`~/.claude/settings.json`), upstream docs verification (docs.cline.bot, docs.openhands.dev) |
| **correction-note** | **2026-07-16 revalidation**: Claude Code is now available as an ACP agent in OpenHands Agent Canvas via `npx -y @agentclientprotocol/claude-agent-acp`. Cline now offers a "Claude Code" provider option that uses the Claude Max/Pro subscription directly (not just BYOK). The subscription login path (macOS Keychain or `~/.claude/.credentials.json`) takes priority over `ANTHROPIC_API_KEY`.

---

## Vendor: OpenAI

| Field | Value |
|---|---|
| **Sanitized source** | `claude --help` shows no OpenAI integration flags, config paths, or routing options. Settings file contains only Anthropic model selection (`"model": "claude-fable-5[1m]"`). Auth section references `ANTHROPIC_API_KEY`, OAuth/keychain exclusively. |
| **Sanitized summary** | Claude Code is a native Anthropic-only tool. No OpenAI vendor support, no external model routing surface. The tool uses only Anthropic's own models and API. |
| **Support state** | not supported — native vendor (Anthropic) only |

---

## Vendor: Anthropic

| Field | Value |
|---|---|
| **Sanitized source** | `claude --help` shows auth via `ANTHROPIC_API_KEY` or OAuth/keychain; settings file active model is `"model": "claude-fable-5[1m]"`. `--model <model>` accepts Anthropic model names and aliases. Help text references "(Bedrock/Vertex/Foundry) use their own" in the vendor selection context, confirming 3P provider support exists for enterprise deployments. |
| **Sanitized summary** | Anthropic is Claude Code's primary native vendor. Key mechanism: `ANTHROPIC_API_KEY` env var or OAuth/keychain login. Model selection via CLI flag (`--model`) or settings file (`"model"` field). All-models granularity — any Anthropic model available to the account can be selected by name. **3P provider support** confirmed for AWS Bedrock, Google Vertex AI, and Foundry enterprise routing — these providers "use their own credentials" per help text. |
| **Support state** | verified native (vendor account + ANTHROPIC_API_KEY) with 3P provider extension (Bedrock/Vertex/Foundry) |

---

## Vendor: Google (Gemini)

| Field | Value |
|---|---|
| **Sanitized source** | No Google/Gemini integration flags, config paths, or routing options in `claude --help` or settings file. |
| **Sanitized summary** | Google/Gemini models are not accessible through Claude Code. The tool has no external vendor routing surface. |
| **Support state** | not supported — native vendor (Anthropic) only |

---

## Vendor: OpenRouter

| Field | Value |
|---|---|
| **Sanitized source** | `claude gateway` subcommand exists but is for "enterprise auth/telemetry gateway" — not an OpenRouter proxy. No OpenRouter-specific flags or config paths. Help mentions "3P providers" in the auth context only (likely third-party enterprise auth, not model routing). |
| **Sanitized summary** | OpenRouter is not a supported vendor. The `gateway` subcommand is for Anthropic's enterprise auth gateway, not OpenRouter's model routing API. No mechanism to route Claude Code through OpenRouter. |
| **Support state** | not supported — no external vendor routing surface |

---

## Config surface

| Field | Value |
|---|---|
| **Config file** | `~/.claude/settings.json` (user-global) with `"model"` field for active model selection. Project-level settings in `.claude/` directory (CLAUDE.md, skills, etc.). |
| **Key mechanism** | Native Anthropic only: `ANTHROPIC_API_KEY` env var or OAuth/keychain login. No multi-vendor config surface. |
| **Model granularity** | Single model at a time via `"model"` field in settings or `--model` CLI flag. Any Anthropic model name accepted by the account tier. |

---

## New upstream capabilities (verified 2026-07-16)

### ACP agent in OpenHands Agent Canvas

Claude Code is now available as an ACP agent in OpenHands Agent Canvas. The Agent Server spawns `npx -y @agentclientprotocol/claude-agent-acp` as a subprocess and relays turns via JSON-RPC on stdio. Authentication uses Claude Code's subscription login (macOS Keychain or `~/.claude/.credentials.json`) or `ANTHROPIC_API_KEY`.

### Cline "Claude Code" provider option

Cline now offers a "Claude Code" provider in the BYOK cloud provider table, using the Claude Max/Pro subscription directly. This means Cline can route through Claude Code's own CLI rather than just Anthropic's API key path.

---

## ACP status

| Field | Value |
|---|---|
| **ACP support** | Adapter |
| **Registry ID** | `anthropic/claude-code` |
| **Launch command** | `npx anthropic/claude-code@latest` (adapter package) |
| **Distribution** | npx (npm adapter) |

Claude Code uses an ACP adapter. The `anthropic/claude-code` npm package provides the ACP interface for Claude Code instances.

## Config override at startup

| Field | Value |
|---|---|
| **CLI flag** | No documented `--config` flag |
| **Env var** | No documented env var for config override |

Claude Code does not support startup config override. Config is fixed at user home path (`~/.claude/`).

---

## Projection mode implications for AG

- Claude Code is a **native vendor tool** — it uses only Anthropic's own models and API. No external vendor routing, no key injection surface for other vendors, no custom endpoint configuration.
- Not a target for generic local endpoint propagation or vendor key injection. The only viable path is the `native-vendor` mechanism where AG can suggest model names to use with Claude Code.
