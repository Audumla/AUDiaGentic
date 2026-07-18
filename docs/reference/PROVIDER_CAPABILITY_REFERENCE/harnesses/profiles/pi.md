# Pi Provider — P1 Vendor Verification Evidence (RV353 Corrected)

<a name="pi-evidence"></a>

## Record header

| Field | Value |
|---|---|
| provider-id | `pi` |
| upstream-id | earendil-works/pi-coding-agent (upstream repo/docs currently inaccessible — 404/removed) |
| tool-version | 0.79.8; upstream docs not reachable as of 2026-07-16 |
| verified-at | 2026-07-13 UTC (RV353 correction), 2026-07-16 UTC (upstream accessibility check) |
| evidence-kind | installed-tool CLI probe (`pi --help` Environment Variables section, `pi --list-models`, home-scoped config inspection `~/.pi/agent/models.json`), upstream accessibility check (pi.vercel.app returns 404 for model-providers path; GitHub repo 404) |
| **correction-note** | RV353 finding #1: prior classification "all vendors custom-entries only" is materially false. Installed help proves native env var key support for all P1 vendors plus dozens of additional vendors. Custom entries remain valid for local/custom endpoints but do not replace native vendor injection. **2026-07-16 revalidation**: Upstream docs (pi.vercel.app/guide/model-providers) return 404; GitHub repo earendil-works/pi-coding-agent returns 404. Community ACP adapter `vkozak/pi-acp` (513 stars, updated 28 days ago) confirms Pi is compatible with Agent Client Protocol. Extensions ecosystem active: pi-mcp-adapter, pi-web-access, pi-skills.

---

## Vendor: OpenAI

<a name="pi-openai"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `pi --help` Environment Variables section lists `OPENAI_API_KEY - OpenAI GPT API key`. CLI shows `--provider openai --model gpt-4o-mini` and `--model openai/gpt-4o` syntax. Help examples include provider-prefixed model selection. |
| **Sanitized summary** | OpenAI is a NATIVE built-in vendor in Pi v0.79.8. Key injection via `OPENAI_API_KEY` env var or CLI `--api-key`. Provider can be selected explicitly (`--provider openai`) or implicitly via provider-prefixed model name (`openai/gpt-4o`). Model granularity: all models the provider supports — Pi does not pre-filter OpenAI's catalog. |
| **Support state** | **verified native env var key injection** (`OPENAI_API_KEY`; also `--api-key` CLI fallback) |

---

## Vendor: Anthropic

<a name="pi-anthropic"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `pi --help` Environment Variables section lists `ANTHROPIC_API_KEY - Anthropic Claude API key` and `ANTHROPIC_OAUTH_TOKEN - Anthropic OAuth token (alternative to API key)`. Help shows model cycling examples with `claude-sonnet,claude-haiku,gpt-4o` and thinking level syntax (`sonnet:high`). |
| **Sanitized summary** | Anthropic is a NATIVE built-in vendor in Pi v0.79.8. Key injection via `ANTHROPIC_API_KEY` env var or CLI `--api-key`. OAuth token alternative available via `ANTHROPIC_OAUTH_TOKEN`. Model selection via `--model anthropic/claude-sonnet` or thinking level shorthand (`sonnet:high`). |
| **Support state** | **verified native env var key injection** (`ANTHROPIC_API_KEY`; also `ANTHROPIC_OAUTH_TOKEN` for OAuth; CLI `--api-key` fallback) |

---

## Vendor: Google (Gemini)

<a name="pi-google"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `pi --help` Environment Variables section lists `GEMINI_API_KEY - Google Gemini API key`. Default provider is `google` (`--provider <name> (default: google)`). |
| **Sanitized summary** | Google/Gemini is a NATIVE built-in vendor in Pi v0.79.8 and is the DEFAULT provider. Key injection via `GEMINI_API_KEY` env var or CLI `--api-key`. Provider selected via `--provider google` (default, so implicit). Model selection via model name after setting key. |
| **Support state** | **verified native env var key injection** (`GEMINI_API_KEY`; also `--api-key` CLI fallback; default provider) |

---

## Vendor: OpenRouter

<a name="pi-openrouter"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `pi --help` Environment Variables section lists `OPENROUTER_API_KEY - OpenRouter API key`. |
| **Sanitized summary** | OpenRouter is a NATIVE built-in vendor in Pi v0.79.8. Key injection via `OPENROUTER_API_KEY` env var or CLI `--api-key`. Provider selected via `--provider openrouter`. Model names follow OpenRouter's convention (e.g., `openrouter/anthropic/claude-sonnet`). |
| **Support state** | **verified native env var key injection** (`OPENROUTER_API_KEY`; also `--api-key` CLI fallback) |

---

## Config surface

| Field | Value |
|---|---|
| **Config file** | `~/.pi/agent/models.json` (home-scoped, NOT project-local) |
| **Config shape** | `{ "providers": { "<source-id>": { "baseUrl", "api", "apiKey", "models[]", "compat" } } }`. One provider block per source. Models are explicit `models[]` entries — selectable granularity with `model-filter` applicable. This surface is for CUSTOM/LOCAL endpoints, not required for native vendors. |
| **Key mechanism** | **(a) Native vendor key injection:** env var only — standard vendor API key names (OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, etc.) recognized by installed tool at launch. CLI fallback: `--api-key <key>`. **(b) Custom endpoints:** structured JSON write to `~/.pi/agent/models.json` with `apiKey` field per provider block. |
| **Reload behavior** | Not verified — Pi may require restart to pick up models.json changes. Env vars effective at launch time. |

---

## New upstream capabilities (verified 2026-07-16 from GitHub search)

### ACP compatibility

Community ACP adapter `vkozak/pi-acp` (513 stars, updated 28 days ago) confirms Pi is compatible with Agent Client Protocol. This means Pi could potentially be driven as an external agent in OpenHands Agent Canvas or similar platforms via ACP.

### Active extensions ecosystem

Multiple community extensions exist:
- `pi-mcp-adapter` (Token-efficient MCP adapter for Pi coding agent)
- `pi-web-access` (Web search and content extraction extension)
- `pi-skills` (Skills compatible with Claude Code and Codex CLI)
- `piclaw` (Pi coding agent in a technicolor web trenchcoat docker)

### Upstream docs inaccessible

The upstream documentation at pi.vercel.app/guide/model-providers returns 404. The GitHub repo earendil-works/pi-coding-agent returns 404. The project appears to have been moved or the docs site is down.

---

## ACP status

| Field | Value |
|---|---|
| **ACP support** | None (not listed in registry) |
| **Registry ID** | N/A — not in ACP registry v1.0.0 |

Pi is not currently listed in the ACP registry v1.0.0. No ACP adapter package exists for this provider.

## Config override at startup

| Field | Value |
|---|---|
| **CLI flag** | No documented `--config` flag |
| **Env var** | No documented env var for config override |

Pi does not support startup config override.

---

## Projection mode implications for AG

- **Native-key-injection (env)**: Primary viable path for P1 vendors. AG sets `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or `OPENROUTER_API_KEY` at launch time and Pi recognizes them immediately. Model selection via `--model <provider>/<id>` or `--provider <name>`. This requires NO file mutation — pure environment variable contribution through the launch-env seam.
- **Custom-entries**: Secondary path for local/custom endpoints only. AG writes provider blocks with model entries to `~/.pi/agent/models.json`. This is a user-home write requiring consent if global scope. Model granularity: selectable via explicit `models[]`. NOT needed for P1 vendors since native env injection covers them.
- **Model filtering**: Pi supports glob-based model patterns (`anthropic/*`, `*sonnet*`) and fuzzy matching. AG-side `model-filter` may complement this but the tool's native pattern language is authoritative.

---

## Additional vendor support (P2 observed in help)

The following vendors are recognized via env vars but fall outside P1 scope:
`DEEPSEEK_API_KEY`, `NVIDIA_API_KEY`, `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `XAI_API_KEY`, `FIREWORKS_API_KEY`, `TOGETHER_API_KEY`, `MISTRAL_API_KEY`, `ANT_LING_API_KEY`, `OPENCODE_API_KEY` (OpenCode Zen/Go), Azure OpenAI suite (`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_BASE_URL`, `AZURE_OPENAI_RESOURCE_NAME`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT_MAP`), `Vercel AI Gateway`, `ZAI`, `MINIMAX`, `MOONSHOT`, `KIMI`, `CLOUDFLARE`, `XIAOMI`.
