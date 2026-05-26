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

    from audiagentic.foundation.system.process import StartupLock
    from audiagentic.runtime.home import global_harness_runtime
    from audiagentic.runtime.rig.registry import (
        ensure_rig_state,
        reap_orphan_rigs,
        write_rig_state,
    )

    with StartupLock(global_harness_runtime() / "rig" / "start.lock"):
        state = ensure_rig_state(rig_port, model=profile_name)
        if state is not None:
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
            raise SystemExit(
                completed.stderr.strip() or completed.stdout.strip() or "Failed to launch embedded rig."
            )

        payload = json.loads(completed.stdout.strip())
        endpoint = payload["base_url"]
        pid = int(payload["pid"])
        write_rig_state(pid, rig_port, endpoint, profile_name)
        os.environ["AUDIAGENTIC_AG_BASE_URL"] = endpoint
        os.environ.setdefault("AUDIAGENTIC_AG_MODEL", model_id)
        return endpoint, model_id, pid, True



from audiagentic.runtime.rig.models import (
    load_model_profile,
    query_server_model,
    query_server_version,
)

__all__ = [
    "launch_rig_if_needed",
    "load_model_profile",
    "query_server_model",
    "query_server_version",
]
