"""Local OpenAI-compatible provider adapter."""
from __future__ import annotations

from audiagentic.components.providers.adapters._stubs import make_ok_stub

run = make_ok_stub("local-openai", derive_id_from_ctx=True)
