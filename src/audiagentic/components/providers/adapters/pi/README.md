# providers/adapters/pi/

Pi provider descriptor area.

This folder currently defines Pi-specific descriptor metadata. Pi runtime-heavy behavior lives under `runtime/harness/pi/`, so this adapter area stays intentionally thin.

## Vendor key injection mechanism (verified v0.79.8)

**Native env var key injection for P1 vendors.** Installed help proves native recognition of standard vendor API keys: `OPENAI_API_KEY` (OpenAI), `ANTHROPIC_API_KEY` / `ANTHROPIC_OAUTH_TOKEN` (Anthropic), `GEMINI_API_KEY` (Google Gemini), `OPENROUTER_API_KEY` (OpenRouter). Provider can be selected via `--provider <name>` or implicitly through provider-prefixed model name (`--model openai/gpt-4o`). Google is the default provider. CLI fallback: `--api-key <key>`. This requires NO file mutation — pure environment variable contribution through the launch-env seam.

**Custom-entries for local/custom endpoints only.** `~/.pi/agent/models.json` with `providers.<id>` blocks carrying `baseUrl`, `api`, `apiKey`, `models[]`, `compat`. Selectable model granularity via explicit entries; applicable when the endpoint is not a recognized native vendor. Model-filter patterns (`anthropic/*`, `*sonnet*`) supported natively by Pi's model cycling language.

## Capability matrix

Full provider × vendor support matrix: see [PROVIDER_MODEL_ENDPOINT_CAPABILITIES.md](../../../../../../docs/reference/PROVIDER_MODEL_ENDPOINT_CAPABILITIES.md#agent-provider--vendor-support-matrix)
Pi-specific evidence: [model-source-evidence/pi.md](../../../../../../docs/reference/model-source-evidence/pi.md)
