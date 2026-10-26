"""Pure construction of private provider packets from explicitly owned inputs.

Packets contain rendered prompts and are runtime-only: do not log or publish
them. This helper resolves no provider/profile/context and reads no file. The
execution owner supplies the trusted local root; metadata is correlation only.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any


def build_provider_packet(
    *, execution_root: Path, request_id: str, profile: Mapping[str, Any],
    prompt_profile_id: str, prompt_template_name: str | None,
    prompt_template_digest: str | None, prompt_definition_fingerprint: str | None,
    model_id: str | None, dispatch_prompt: str, source: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    template_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Map supplied facts; optional mappings pass through without normalization.

    The caller owns defaults and model fallback. There is no request-record
    lookup or new validation authority here. Stream controls retain the existing
    shallow-copy behavior; all other values retain the existing packet mapping.
    """
    return {
        "request-id": request_id,
        "job-id": request_id,
        "execution-profile-id": profile["profile_id"],
        "prompt-profile-id": prompt_profile_id,
        "prompt-template-name": prompt_template_name,
        "prompt-template-digest": prompt_template_digest,
        "prompt-definition-fingerprint": prompt_definition_fingerprint,
        "provider-id": profile["provider_id"],
        "model-id": model_id,
        "model-alias": profile.get("model_alias"),
        "prompt-body": dispatch_prompt,
        "params": profile.get("params", {}),
        "working-root": str(execution_root.resolve()),
        "stream-controls": dict(profile.get("params", {}).get("stream-controls") or {}),
        "source": source,
        "metadata": metadata,
        "template-context": template_context,
    }
