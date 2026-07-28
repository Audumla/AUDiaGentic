"""Shared embedded rig lifecycle management.

Both pi and opencode harnesses use the same embedded rig (llama-server).
This module owns launch, reuse detection, cleanup, and server queries so
neither harness duplicates that logic or imports from the other.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from audiagentic.runtime.rig.models import (
    load_model_profile,
    query_server_model,
    query_server_version,
)


@dataclass(frozen=True)
class RigConnection:
    endpoint: str
    model: str
    embedded: bool
    attachment: object | None = None


def launch_rig_if_needed(
    model: str,
    profile_name: str,
    model_profile: dict[str, object],
    rig_port: int,
    model_id: str = "audiagentic-rig",
) -> RigConnection:
    """Return an external connection or a leased embedded-rig connection.

    For embedded rig: model is the configurable model ID passed to the agent.
    For external backend: model is the model name from config/env, unchanged.
    Embedded lifecycle ownership is represented by a foundation service lease,
    never a starter-local PID.
    """
    if os.environ.get("AUDIAGENTIC_AG_BASE_URL"):
        return RigConnection(os.environ["AUDIAGENTIC_AG_BASE_URL"], model, False)
    if not model_profile.get("model_file"):
        return RigConnection(f"http://127.0.0.1:{rig_port}/v1", model, False)

    from audiagentic.runtime.rig.service import start_or_attach_embedded_rig

    attachment = start_or_attach_embedded_rig(
        profile_name=profile_name,
        rig_port=rig_port,
        model_id=model_id,
    )
    os.environ["AUDIAGENTIC_AG_BASE_URL"] = attachment.endpoint
    os.environ.setdefault("AUDIAGENTIC_AG_MODEL", model_id)
    return RigConnection(attachment.endpoint, model_id, True, attachment)

__all__ = [
    "launch_rig_if_needed",
    "RigConnection",
    "load_model_profile",
    "query_server_model",
    "query_server_version",
]
