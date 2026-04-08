# Local OpenAI-compatible tag execution implementation

Provider: local OpenAI-compatible endpoints (vLLM, llama.cpp server proxies, litellm-style
gateways, etc.)  
Compliance level: C — backend only  
Execution state: NOT IMPLEMENTED
Phase: 4.4

## Confirmation summary

OpenAI-compatible local servers are model endpoints. They are configured in host clients
such as Continue or Cline by setting the provider to `openai` and changing the API base.
They do not own the user-facing prompt surface.

Therefore they must **not** be specified as independent prompt-tag executors.

## Architectural position

This provider category participates only as:
- model transport
- model routing backend
- cost/performance target
- policy-enforced endpoint beneath a real client surface

Canonical tag recognition must happen in:
- Continue
- Cline
- Codex wrapper
- Claude SDK shim
- Gemini wrapper/host
- or another client that owns the actual prompt surface

## What to document / implement instead

For local OpenAI-compatible backends, define:
- supported API base URL(s)
- model names / aliases
- timeout and auth settings
- which host clients can target the backend
- whether review workloads should prefer a different model tier

Do **not** create:
- provider-native `@tag` rules
- backend-native review loop logic
- backend-native stage restrictions

Those belong in the client.

## Exact files/settings to plan for later implementation

Client-side only:
- Continue `config.yaml` or Cline provider settings
- provider selection catalog entries
- host-client adapter config

Backend-side:
- server auth and endpoint configuration
- model routing policy
- health checks

## Risks / limits

- describing backend-only providers as tag-aware would be misleading
- if multiple clients target the same backend, canonical tag behavior still belongs to each client surface

## Recommendation

Keep this provider family explicitly marked as backend-only. Do not spend implementation
effort trying to add tag recognition at the raw model endpoint layer.

## Related docs

- `docs/implementation/providers/26_Local_OpenAI_Compatible_Prompt_Trigger_Runbook.md`




