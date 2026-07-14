# Cline Provider — Vendor Verification Evidence

<a name="cline-evidence"></a>

## Record header

| Field | Value |
|---|---|
| provider-id | `cline` |
| upstream-id | cline CLI (npm) |
| tool-version | 3.0.3 |
| verified-at | 2026-07-13 UTC |
| evidence-kind | installed-tool CLI probe (`cline --help`, `cline auth --help`), config inspection (`~/.cline/`) |

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
| **Sanitized source** | `cline auth gemini` returns error "provider 'gemini' requires API key setup (use subcommand: auth --provider gemini --apikey <key> --modelid <id>)". Confirms Gemini is a recognized provider id. |
| **Sanitized summary** | Google/Gemini support via generic provider routing with `--provider gemini`. Requires `--apikey`, `--modelid`, optional `--baseurl`. Same auth surface as other vendors. |
| **Support state** | **verified native via auth surface** (gemini provider id recognized) |

---

## Vendor: OpenRouter

<a name="cline-openrouter"></a>

| Field | Value |
|---|---|
| **Sanitized source** | No specific "openrouter" provider id tested. The generic `--provider`, `--apikey`, `--modelid`, `--baseurl` surface suggests any vendor with an API-compatible endpoint can be configured, including OpenRouter via custom base URL. |
| **Sanitized summary** | OpenRouter support likely viable through generic provider configuration: `cline auth --provider <custom-id> --apikey <key> --modelid <id> --baseurl https://openrouter.ai/api/v1`. Not directly tested with a named "openrouter" provider id, but the surface supports arbitrary endpoints. |
| **Support state** | **blocked: not a listed provider id; possible via custom endpoint configuration — not tested with live credentials** |

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
