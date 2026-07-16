# Cline Provider — Vendor Verification Evidence

<a name="cline-evidence"></a>

## Record header

| Field | Value |
|---|---|
| provider-id | `cline` |
| upstream-id | cline CLI (npm) + Cline SDK (@cline/sdk) |
| tool-version | 3.0.3; upstream docs revalidated 2026-07-16 |
| verified-at | 2026-07-13 UTC, 2026-07-16 UTC (upstream doc revalidation) |
| evidence-kind | installed-tool CLI probe (`cline --help`, `cline auth --help`), config inspection (`~/.cline/`), upstream docs verification (docs.cline.bot) |
| **correction-note** | **2026-07-16 revalidation**: Cline has been significantly restructured. Three provider paths: (1) Cline usage-billing (OAuth via Google/GitHub/email, no API key needed), (2) ClinePass ($9.99/month subscription with 2-5x rate limits for open coding models), (3) BYOK (Bring Your Own Key) for cloud providers and local runtimes. The old `cline auth <provider>` subcommand still works for BYOK, but the new architecture adds IDE settings UI (API Provider dropdown + API Key field + Model dropdown). ClinePass is a new subscription provider with GLM, Kimi, DeepSeek, MiMo models. OpenRouter now has a named provider id in Cline. Custom base URL supported per provider.

---

## Vendor: OpenAI

<a name="cline-openai"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `cline auth openai` returns error "provider 'openai-compatible' requires API key setup (use subcommand: auth --provider openai-compatible --apikey <key> --modelid <id>)". Default provider id is "cline" with openai-compatible fallback. |
| **Sanitized summary** | OpenAI support via generic provider routing. Configured through `cline auth` with `--provider openai-compatible`, `--apikey <key>`, `--modelid <model-id>`, optional `--baseurl`. API key can be set via CLI flag `-k, --key <api-key>` or persist in `~/.cline/` config. |
| **Support state** | **verified native via auth surface** (openai-compatible provider with apikey/modelid/baseurl parameters) |

---

## Vendor: Anthropic

<a name="cline-anthropic"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `cline auth anthropic` returns error "provider 'anthropic' requires API key setup (use subcommand: auth --provider anthropic --apikey <key> --modelid <id>)". Confirms Anthropic is a recognized provider id. |
| **Sanitized summary** | Anthropic support via generic provider routing with `--provider anthropic`. Requires `--apikey`, `--modelid`, optional `--baseurl` for custom endpoint. Same auth surface as OpenAI. |
| **Support state** | **verified native via auth surface** (anthropic provider id recognized) |

---

## Vendor: Google (Gemini)

<a name="cline-google"></a>

| Field | Value |
|---|---|
| **Sanitized source** | Upstream docs confirm "Google Gemini" is a named provider in Cline's API Provider dropdown with its own "Gemini API Key" field. CLI: `cline auth --provider gemini --apikey <key> --modelid <id>` still works. |
| **Sanitized summary** | Google/Gemini support via named provider id "Google Gemini". IDE: select from API Provider dropdown, paste key into "Gemini API Key" field, select model. CLI: `cline auth --provider gemini --apikey <key> --modelid <id>`. |
| **Support state** | **verified native via named provider id** (google-gemini) |

---

## New upstream capabilities (verified 2026-07-16 from docs.cline.bot)

### Three provider paths

Cline now offers three distinct provider paths:

| Path | Description |
|---|---|
| **Cline (usage-billing)** | Sign in with Google/GitHub/email; no API key needed; built-in billing and free model options; access to multiple providers from one account |
| **ClinePass** | Flat $9.99/month subscription; 2-5x API rate limits; curated open coding models (GLM, Kimi, DeepSeek, MiMo) |
| **BYOK (Bring Your Own Key)** | Use your own provider credentials for cloud providers (OpenRouter, Anthropic, OpenAI, Google Gemini, AWS Bedrock, DeepSeek) or local runtimes (Ollama, LM Studio) |

### IDE settings UI

The IDE settings page provides an API Provider dropdown with named providers, an API Key field per provider, and a Model dropdown. The CLI `cline auth` subcommand still works for BYOK.

### OpenRouter now named provider

OpenRouter has its own provider id in Cline's API Provider dropdown. Custom base URL is supported ("Use custom base URL" checkbox).

### SDK architecture

Cline now exposes an agent core SDK (`@cline/sdk`) that powers the CLI, Kanban, VS Code extension, and JetBrains plugin. The SDK can be used to build custom applications.

---

## Vendor: OpenRouter

<a name="cline-openrouter"></a>

| Field | Value |
|---|---|
| **Sanitized source** | Upstream docs confirm OpenRouter is now a named provider in Cline's API Provider dropdown. Custom base URL supported ("Use custom base URL" checkbox). The generic `--provider`, `--apikey`, `--modelid`, `--baseurl` surface also supports arbitrary endpoints. |
| **Sanitized summary** | OpenRouter is now a named provider id in Cline v3+. IDE: select "OpenRouter" from API Provider dropdown, paste key into "OpenRouter API Key" field, select model. CLI: `cline auth --provider openrouter --apikey <key>`. Custom base URL supported. |
| **Support state** | **verified native via named provider id** (openrouter; also custom endpoint configuration) |

---

## Config surface

| Field | Value |
|---|---|
| **Config file** | `~/.cline/` directory with subdirectories for cron, data, kanban, worktrees. Auth state persists per provider id. No project-local config surface discovered. |
| **Key mechanism** | CLI flags: `-k, --key <api-key>` (per-run override), `auth --provider <id> --apikey <key>` (persistent). Model selection via `-m, --model <model-id>`. Base URL override via auth `--baseurl <url>`. |
| **Model granularity** | Single active model per session. Provider id determines the API routing; modelid selects within that provider's catalog. |
| **Reload behavior** | Cline reads config at startup. Auth state persisted in `~/.cline/` — changes require restart. |

---

## Projection mode implications for AG

- **Native-key-injection (config)**: Viable through `cline auth --provider <id> --apikey <key>` for persistent configuration, or `-k --key` for per-run override. Supports OpenAI-compatible, Anthropic, Gemini provider ids natively. Requires user-home config writes.
- **Custom-entries**: Not applicable — cline uses named provider ids with key/model selection, not a catalog of custom endpoints. Single active model at a time.
- **Limitation**: No project-local config surface discovered — all state is in `~/.cline/` (user-global). AG projection would require consent for home-scope writes or launch-time CLI flag injection.
