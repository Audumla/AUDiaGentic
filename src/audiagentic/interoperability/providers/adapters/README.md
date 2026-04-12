# interoperability/providers/adapters/

## Purpose
Provider-specific adapter implementations. Each file encapsulates the full execution wiring for one external AI provider.

## Ownership
- Provider subprocess invocation and argument construction
- Provider-specific event extraction and stream parsing
- Provider-specific completion normalization
- Stream sink configuration for each provider

## Must NOT Own
- Cross-provider logic (→ parent `providers/` root)
- Provider configuration loading (→ `foundation/config/`)
- Job orchestration (→ `execution/jobs/`)

## Allowed Dependencies
- `foundation/contracts` — errors, validation
- `foundation/config` — provider config types
- `interoperability/protocols/streaming` — sink construction and event types
- `execution/jobs` — prompt_launch and prompt_parser (gemini only — documented seam)

## One file per provider

| File | Provider |
|------|----------|
| `claude.py` | Anthropic Claude |
| `cline.py` | Cline |
| `codex.py` | OpenAI Codex |
| `gemini.py` | Google Gemini |
| `qwen.py` | Qwen |
| `opencode.py` | opencode |
| `copilot.py` | GitHub Copilot |

## Adding a new provider
1. Create `<provider_id>.py` implementing the adapter interface
2. Add entry to `interoperability/providers/execution.py` `_ADAPTER_MODULES` dict
3. Add provider config to `.audiagentic/providers.yaml`
4. Add integration test under `tests/integration/providers/`
