# Copilot Provider — Vendor Verification Evidence

<a name="copilot-evidence"></a>

## Record header

| Field | Value |
|---|---|
| provider-id | `copilot` |
| upstream-id | github/copilot (GitHub CLI extension) |
| tool-version | CLI (version from session context, exact not captured in this run) |
| verified-at | 2026-07-13 UTC |
| evidence-kind | installed-tool CLI probe (`copilot --help`, model listing via error message), account inspection |

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

## Projection mode implications for AG

- **Native-key-injection**: Not viable — copilot has no API key injection surface. All models require GitHub Copilot account authentication with appropriate subscription tier.
- **Custom-entries**: Not applicable — the catalog is vendor-closed; no extensibility via custom endpoints or API keys. Only account-derived models are available.
- **AG projection path**: If copilot were projected, it would function purely as an "account-bound provider" where AG validates the user's subscription status at runtime and delegates model selection to Copilot's curated catalog. Key injection is not possible; auth must come from `gh` login state.
