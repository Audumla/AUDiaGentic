# providers/adapters/local_openai/

Local OpenAI bridge adapter.

Owns descriptor and execution bridge for OpenAI-compatible local endpoints. This area focuses on runtime access to external/local OpenAI-style servers rather than CLI installation flows.

Set `providers.local-openai.base-url` in your user or project settings for a machine-local
endpoint; without it the OpenAI default applies. the `home` setting and `AUDIAGENTIC_REPO_ROOT` select the
global and project roots.
