from ...descriptors.base import ProviderDescriptor, ProviderPermissions
from ...descriptors.registry import register

register(ProviderDescriptor(
    provider_id="local-openai",
    prompt_aliases=("lo",),
    display_name="Local OpenAI Bridge",
    description="Generic OpenAI-compatible REST endpoint. Points to any locally hosted model server (llama.cpp, Ollama, vLLM, etc.).",
    url="https://platform.openai.com/docs/api-reference",
    access_mode="none",
    cli_probe=None,
    host_capabilities=(),
    permissions=ProviderPermissions(
        can_write_files=False,
        can_execute_shell=False,
        can_browse_web=False,
        can_read_env=False,
        notes="OpenAI-compatible REST endpoint; no autonomous tool use",
    ),
    agent_files=(),
))
