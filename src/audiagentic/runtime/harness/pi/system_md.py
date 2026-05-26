"""Shim — system prompt injection moved to harness/system_prompt.py."""
from audiagentic.runtime.harness.system_prompt import (
    apply_system_prompt_injections as apply_system_md_injections,
)
from audiagentic.runtime.harness.system_prompt import (
    build_system_prompt_injections as build_system_md_injections,
)

__all__ = ["apply_system_md_injections", "build_system_md_injections"]
