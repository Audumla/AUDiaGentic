"""Resolve a ChatGPT URL to its existing gateway queue before admission."""
from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.components.providers.adapters.gpt_auto.urls import parse_provider_session_id
from . import sessions_store


def resolve_conversation_owner(project_root: Path, chat_url: str, session_id: str | None) -> str | None:
    conversation = parse_provider_session_id(chat_url)
    owners = []
    for record in sessions_store.list_session_records(project_root):
        binding = record.get("binding") or {}
        metadata = sessions_store.session_provider_metadata(record)
        provider = binding.get("provider-id") or sessions_store.session_provider_id(record) or ""
        ref = binding.get("provider-session-ref") or metadata.get("provider-session-id")
        if not ref:
            ref = parse_provider_session_id(metadata.get("chat-url") or "")
        if provider.startswith("gpt-auto") and ref == conversation:
            owners.append(record)
    # Closed predecessors must not compete with their live successor.
    live = [record for record in owners if record.get("state") not in {"closed", "expired", "failed"}]
    candidates = live or owners
    if session_id and any(record["session-id"] == session_id for record in candidates):
        return session_id
    if len(candidates) > 1 or (session_id and candidates):
        raise AudiaGenticError(
            code="VAL-AGW-151", kind="agents",
            message="ChatGPT URL has conflicting gateway session ownership",
            details={"session-ids": [record["session-id"] for record in candidates]},
        )
    return candidates[0]["session-id"] if candidates else session_id
