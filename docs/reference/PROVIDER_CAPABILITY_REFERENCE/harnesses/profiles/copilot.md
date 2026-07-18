# Copilot Provider — Vendor Verification Evidence

<a name="copilot-evidence"></a>

## Record header

| Field | Value |
|---|---|
| provider-id | `copilot` |
| upstream-id | github/copilot (GitHub CLI extension) + MCP integration (2026-07-16) |
| tool-version | CLI (version from session context, exact not captured in this run); upstream docs revalidated 2026-07-16 |
| verified-at | 2026-07-13 UTC, 2026-07-16 UTC (upstream doc revalidation) |
| evidence-kind | installed-tool CLI probe (`copilot --help`, model listing via error message), account inspection, upstream docs verification (docs.github.com) |
| **correction-note** | **2026-07-16 revalidation**: Copilot now supports MCP (Model Context Protocol) for extending capabilities. GitHub MCP Server available with toolsets and enterprise configuration. MCP support is IDE-integrated: "Using Model Context Protocol in your IDE". This represents a significant new capability — Copilot can now integrate external tools via MCP servers, similar to other agents. However, the model catalog remains vendor-closed (curated from OpenAI, Anthropic, Google partners).

---

## Vendor: OpenAI

<a name="copilot-openai"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `copilot --help` shows `"gpt-5.2", "gpt-5.1-codex"` in the model choices enum (from help output and error messages during probe runs). |
| **Sanitized summary** | OpenAI models are part of the account-derived catalog: GPT 5.2 and gpt-5.1-codex confirmed present. Selection via `--model <model>` flag; requires GitHub Copilot subscription. No env-var key injection surface — authentication is account-bound through GitHub login. |
| **Support state** | **verified native (account-based)** |

---

## Vendor: Anthropic

<a name="copilot-anthropic"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `copilot --help` shows `"claude-sonnet-4.6", "claude-sonnet-4.5", "claude-haiku-4.5", "claude-opus-4.6", "claude-opus-4.6-fast", "claude-opus-4.5"` in the model choices enum. |
| **Sanitized summary** | Anthropic Claude models are fully integrated into the Copilot catalog: Claude Sonnet 4.x series, Haiku 4.5, and Claude Opus 4.x series confirmed present. Selection via `--model <model>` flag. No env-var key injection — authentication is account-bound through GitHub login with subscription tiers controlling access. |
| **Support state** | **verified native (account-based)** |

---

## Vendor: Google (Gemini)

<a name="copilot-google"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `copilot --help` shows `"gemini-3-pro-preview"` in the model choices enum. |
| **Sanitized summary** | Google Gemini is present in the Copilot catalog: gemini-3-pro-preview confirmed available. Selection via `--model <model>` flag. Account-based authentication through GitHub; no env-var key injection surface. |
| **Support state** | **verified native (account-based)** |

---

## Vendor: OpenRouter

<a name="copilot-openrouter"></a>

| Field | Value |
|---|---|
| **Sanitized source** | No OpenRouter models observed in `copilot --help` model enum. Copilot does not expose a generic vendor-routing surface — the catalog is curated from GitHub's partnership integrations (OpenAI, Anthropic, Google). |
| **Sanitized summary** | OpenRouter is not directly supported. The Copilot model catalog is vendor-closed; custom provider injection via API key or base URL is not available. Only account-derived models are selectable. |
| **Support state** | **blocked: not in catalog — no vendor-routing surface** |

---

## Config surface

| Field | Value |
|---|---|
| **Config file** | No structured config file discovered. Model selection and auth state managed through GitHub CLI extension infrastructure (`gh` authentication tokens). Project-local `.copilot/config.toml` pattern not observed — all configuration is account-global or CLI-flag-driven. |
| **Key mechanism** | Pure account-based. Authentication delegated to `gh` (GitHub CLI) OAuth token. No env-var injection for API keys, no per-vendor key configuration. Model selection via `--model <model>` flag only. |
| **Model granularity** | Curated subset of vendor models available through Copilot subscription tiers. One active model per session via `--model`. The catalog is not extensible with custom endpoints. |
| **Reload behavior** | Reads auth state and model list at startup. No live reload observed — restart required for model changes. |

---

## New upstream capabilities (verified 2026-07-16 from docs.github.com)

### MCP (Model Context Protocol) support

Copilot now supports MCP for extending capabilities. The GitHub MCP Server allows Copilot to interact with repositories, issues, pull requests, and other GitHub features directly from Copilot Chat in your IDE.

Key MCP capabilities:
- Extending Copilot Chat with external MCP servers
- GitHub MCP Server (with toolsets and enterprise configuration)
- Customizable MCP registry per IDE

This represents a significant new integration surface — Copilot can now consume tools from external MCP servers, similar to other agents like OpenHands and Cline. However, the model catalog remains vendor-closed; MCP extends *capabilities*, not *model access*.

### Agent Client Protocol (ACP) support

Copilot Chat is listed as a supported ACP agent in OpenHands Agent Canvas, meaning it can be driven as an external agent via ACP's JSON-RPC over stdio protocol. This places Copilot alongside Claude Code and Gemini CLI as an ACP-compatible agent.

---

## ACP status

| Field | Value |
|---|---|
| **ACP support** | Native |
| **Registry ID** | `github/copilot-cli` |
| **Launch command** | `npx @anthropic/claude-code@latest` (adapter for copilot) |
| **Distribution** | npx (npm adapter) |

GitHub Copilot CLI uses an ACP adapter via the `anthropic/claude-code` npm package. This is unusual — Copilot is served through Claude's adapter infrastructure.

## Config override at startup

| Field | Value |
|---|---|
| **CLI flag** | No documented `--config` flag |
| **Env var** | No documented env var for config override |

GitHub Copilot CLI does not support startup config override.

---

## Projection mode implications for AG

- **Native-key-injection**: Not viable — copilot has no API key injection surface. All models require GitHub Copilot account authentication with appropriate subscription tier.
- **Custom-entries**: Not applicable — the catalog is vendor-closed; no extensibility via custom endpoints or API keys. Only account-derived models are available.
- **AG projection path**: If copilot were projected, it would function purely as an "account-bound provider" where AG validates the user's subscription status at runtime and delegates model selection to Copilot's curated catalog. Key injection is not possible; auth must come from `gh` login state.
