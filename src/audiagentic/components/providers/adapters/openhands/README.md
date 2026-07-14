# providers/adapters/openhands/

OpenHands provider adapter.

Owns OpenHands-specific descriptor, execution bridge, and managed surface content. Shared provider lifecycle and catalog behavior stay outside this folder.

## Vendor key injection mechanism (verified v1.16.0 / SDK 1.21.0)

**Launch-env route via LiteLLM prefix — env var recognition confirmed, execution requires authenticated test.** P1 vendors accepted through LiteLLM model prefix convention (`openai/<id>`, `anthropic/<id>`, `gemini/<id>`, `openrouter/<vendor>/<id>`). Key injection mechanism: set `LLM_API_KEY` (unified for all vendors), `LLM_BASE_URL` (optional override), `LLM_MODEL=<prefix>/<model-id>` with `--override-with-envs`. The env vars are recognized by startup logic and passed to LiteLLM; isolated authenticated launch against non-OpenAI vendor endpoints not yet tested. Structured `[llm]` section in `.openhands/config.toml` is the fallback path — exact key names inferred from SDK docs (unverified vs installed version). Single active model per session — not a multi-model catalog.

## Capability matrix

Full provider × vendor support matrix: see [PROVIDER_MODEL_ENDPOINT_CAPABILITIES.md](../../../../../../docs/reference/PROVIDER_MODEL_ENDPOINT_CAPABILITIES.md#agent-provider--vendor-support-matrix)
OpenHands-specific evidence: [model-source-evidence/openhands.md](../../../../../../docs/reference/model-source-evidence/openhands.md)
