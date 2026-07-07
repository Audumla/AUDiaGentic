"""Shared embedded rig lifecycle management.

Both pi and opencode harnesses use the same embedded rig (llama-server).
This module owns launch, reuse detection, cleanup, and server queries so
neither harness duplicates that logic or imports from the other.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error
from audiagentic.runtime.rig.models import (
    load_model_profile,
    query_server_model,
    query_server_version,
)


def _rig_launch_error(code_number: int, message: str, **details: object) -> AudiaGenticError:
    return make_error(
        prefix="EXT",
        component="RIG",
        number=code_number,
        kind="runtime-rig",
        message=message,
        details=details,
    )


def launch_rig_if_needed(
    model: str,
    profile_name: str,
    model_profile: dict[str, object],
    rig_port: int,
    model_id: str = "audiagentic-rig",
) -> tuple[str, str, int | None, bool]:
    """Return (endpoint, model, rig_pid, manages_rig).

    For embedded rig: model is the configurable model ID passed to the agent.
    For external backend: model is the model name from config/env, unchanged.
    manages_rig is True when connected to an embedded rig (started now or reused).
    rig_pid is set only when *this* call started the rig; None means reused or external.
    """
    if os.environ.get("AUDIAGENTIC_AG_BASE_URL"):
        return os.environ["AUDIAGENTIC_AG_BASE_URL"], model, None, False
    if not model_profile.get("model_file"):
        return f"http://127.0.0.1:{rig_port}/v1", model, None, False

    from audiagentic.runtime.rig.registry import (
        ensure_rig_state,
        reap_orphan_rigs,
        register_client,
        rig_start_lock,
        write_rig_state,
    )

    with rig_start_lock():
        state = ensure_rig_state(rig_port, model=profile_name)
        if state is not None:
            # Register while still holding the lock: a departing last client
            # counts clients under the same lock, so it can never miss us and
            # kill the rig we just decided to reuse (PR04 start/stop race).
            register_client()
            endpoint = str(state["endpoint"])
            os.environ["AUDIAGENTIC_AG_BASE_URL"] = endpoint
            return endpoint, model_id, None, True

        reap_orphan_rigs()

        env = os.environ.copy()
        completed = subprocess.run(
            [sys.executable, "-m", "audiagentic.runtime.rig.embedded.launch",
             "--model-profile", profile_name, "--port", str(rig_port), "--background", "--json"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "Failed to launch embedded rig."
            raise _rig_launch_error(
                4,
                detail,
                returncode=completed.returncode,
                profile=profile_name,
                port=rig_port,
            )

        payload = json.loads(completed.stdout.strip())
        endpoint = payload["base_url"]
        pid = int(payload["pid"])
        write_rig_state(pid, rig_port, endpoint, profile_name)
        register_client()
        os.environ["AUDIAGENTIC_AG_BASE_URL"] = endpoint
        os.environ.setdefault("AUDIAGENTIC_AG_MODEL", model_id)
        return endpoint, model_id, pid, True

__all__ = [
    "launch_rig_if_needed",
    "load_model_profile",
    "query_server_model",
    "query_server_version",
]
