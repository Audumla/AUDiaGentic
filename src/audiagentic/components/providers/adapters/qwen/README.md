# providers/adapters/qwen/

Qwen provider adapter.

Owns Qwen-specific descriptor, execution bridge, and managed surface content. Shared routing, health, and catalog logic remain in provider services.

## Vendor key injection mechanism (verified v0.13.1)

**Multi-auth-type model selection.** P1 vendor support via `--auth-type`: OpenAI (`--auth-type openai` + `--openai-api-key`), Anthropic (`--auth-type anthropic`; env var expected, exact CLI flag blocked without isolated test), Google/Gemini (`--auth-type gemini` or `--auth-type vertex-ai`; key mechanism blocked). Settings at `~/.qwen/settings.json` carry `"security.auth.selectedType"` and `"model.name"`. Only ONE auth type active at a time — Qwen switches auth mode per type, not simultaneous multi-vendor enablement. Single model at a time via `-m <model>` or settings pointer.

## Capability matrix

Full provider × vendor support matrix: see [endpoints/provider-model-endpoints.md](../../../../../../docs/reference/PROVIDER_CAPABILITY_REFERENCE/endpoints/provider-model-endpoints.md#agent-provider--vendor-support-matrix)
Qwen-specific evidence: [harnesses/profiles/qwen.md](../../../../../../docs/reference/PROVIDER_CAPABILITY_REFERENCE/harnesses/profiles/qwen.md)
