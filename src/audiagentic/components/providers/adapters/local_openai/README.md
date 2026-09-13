# providers/adapters/local_openai/

Local OpenAI bridge adapter.

Owns descriptor and execution bridge for OpenAI-compatible local endpoints. This area focuses on runtime access to external/local OpenAI-style servers rather than CLI installation flows.

Set `AUDIAGENTIC_LOCAL_PROVIDER_BASE_URL` for a machine-local endpoint when
the provider configuration does not specify `api-base-url`; explicit provider
configuration wins. Use `AUDIAGENTIC_RIG_HOST` and `AUDIAGENTIC_RIG_PORT` for
the embedded rig. `AUDIAGENTIC_HOME` and `AUDIAGENTIC_REPO_ROOT` select the
global and project roots.
