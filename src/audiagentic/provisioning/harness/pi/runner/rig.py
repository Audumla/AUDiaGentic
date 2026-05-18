from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def launch_rig_if_needed(
    model: str,
    profile_name: str,
    model_profile: dict[str, object],
    rig_port: int,
    model_id: str = "audiagentic-rig",
) -> tuple[str, str, int | None, bool]:
    """Return (endpoint, model, rig_pid, manages_rig).

    For embedded rig: model is the configurable model ID passed to Pi.
    For external backend: model is the model name from config/env, passed through unchanged.
    manages_rig is True when connected to an embedded rig (started now or reused).
    rig_pid is set only when *this* call started the rig; None means reused or external.
    """
    if os.environ.get("AUDIAGENTIC_AG_BASE_URL"):
        return os.environ["AUDIAGENTIC_AG_BASE_URL"], model, None, False
    if not model_profile.get("model_file"):
        return f"http://127.0.0.1:{rig_port}/v1", model, None, False

    from audiagentic.provisioning.rig.registry import StartupLock, read_rig_state, write_rig_state, reap_orphan_rigs
    from .context import env_with_pythonpath

    with StartupLock():
        state = read_rig_state()
        if state is not None:
            endpoint = str(state["endpoint"])
            os.environ["AUDIAGENTIC_AG_BASE_URL"] = endpoint
            return endpoint, model_id, None, True

        reap_orphan_rigs()

        env = env_with_pythonpath()
        completed = subprocess.run(
            [sys.executable, "-m", "audiagentic.provisioning.rig.embedded.launch",
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


def cleanup_rig(pid: int | None) -> None:
    import os
    import subprocess
    if not pid:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return
    try:
        os.kill(pid, 9)
    except OSError:
        pass


def cleanup_process_tree(pid: int) -> None:
    import os
    import subprocess
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return
    try:
        os.kill(pid, 9)
    except OSError:
        pass
