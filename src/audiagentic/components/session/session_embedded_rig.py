"""Embedded rig operations for the core session component."""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import time
from typing import Any
from urllib.parse import urlparse

from audiagentic.foundation.contracts.output import ComponentOutputEvent


def active_embedded_rig_profile() -> str | None:
    if os.environ.get("AUDIAGENTIC_RIG_TYPE") != "embedded":
        return None
    profile = os.environ.get("AUDIAGENTIC_RIG_PROFILE")
    if isinstance(profile, str) and profile.strip():
        return profile.strip()
    return None


def active_embedded_rig_port() -> int:
    endpoint = os.environ.get("AUDIAGENTIC_AG_BASE_URL")
    if endpoint:
        parsed = urlparse(endpoint)
        if parsed.port is not None:
            return int(parsed.port)
    return 42001


async def update_embedded_rig() -> dict[str, Any]:
    from audiagentic.foundation.system.process import kill_pid
    from audiagentic.runtime.rig.embedded.binaries import update_binaries as _update
    from audiagentic.runtime.rig.embedded.launch import runtime_bin_dir, start_embedded_rig
    from audiagentic.runtime.rig.registry import (
        _clear_rig_state,
        ensure_rig_state,
        read_rig_state,
        write_rig_state,
    )

    def _work(sink):
        out = io.StringIO()
        try:
            bin_dir = runtime_bin_dir()
            active_profile = active_embedded_rig_profile()
            active_state = None
            if active_profile:
                active_state = read_rig_state()
                if active_state is None:
                    active_state = ensure_rig_state(active_embedded_rig_port(), model=active_profile)

            if sink:
                if active_state and active_profile:
                    sink(
                        ComponentOutputEvent(
                            message=(
                                f"[rig] stopping embedded rig '{active_profile}' on "
                                f"{active_state.get('endpoint', 'unknown endpoint')}"
                            )
                        )
                    )
                else:
                    sink(ComponentOutputEvent(message="[rig] updating embedded rig binaries"))

            if active_state and active_profile:
                kill_pid(int(active_state["pid"]))
                deadline = time.time() + 15.0
                while time.time() < deadline:
                    try:
                        os.kill(int(active_state["pid"]), 0)
                    except OSError:
                        break
                    time.sleep(0.25)
                _clear_rig_state()

            with contextlib.redirect_stdout(out):
                _update(target_bin_dir=bin_dir)

            restarted: dict[str, Any] | None = None
            if active_state and active_profile:
                port = int(active_state["port"])
                if sink:
                    sink(ComponentOutputEvent(message=f"[rig] restarting embedded rig '{active_profile}'"))
                launch_result = start_embedded_rig(
                    model_profile=active_profile,
                    port=port,
                    health_timeout=90.0,
                    on_progress=(lambda message: sink(ComponentOutputEvent(message=message))) if sink else None,
                )
                restarted = {
                    "pid": int(launch_result.pid),
                    "port": int(launch_result.port),
                    "base_url": str(launch_result.base_url),
                }
                write_rig_state(
                    int(restarted["pid"]),
                    int(restarted["port"]),
                    str(restarted["base_url"]),
                    active_profile,
                )
                if sink:
                    sink(
                        ComponentOutputEvent(
                            message=(
                                f"[rig] embedded rig '{active_profile}' healthy at "
                                f"{restarted['base_url']}"
                            )
                        )
                    )

            if sink:
                sink(ComponentOutputEvent(message=out.getvalue().strip()))
            return {
                "ok": True,
                "output": out.getvalue().strip(),
                "restarted": restarted is not None,
                "endpoint": restarted["base_url"] if restarted else None,
                "profile": active_profile,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "output": out.getvalue().strip()}

    return await asyncio.to_thread(_work, None)


async def update_global_embedded_rig() -> dict[str, Any]:
    from audiagentic.runtime.home import global_harness_runtime

    def _work(sink):
        return _update_global_embedded_rig_impl(global_harness_runtime(), sink=sink)

    return await asyncio.to_thread(_work, None)


def _update_global_embedded_rig_impl(harness_runtime, *, sink=None) -> dict[str, Any]:
    from audiagentic.runtime.rig.embedded.binaries import update_binaries as _update
    from audiagentic.runtime.rig.embedded.launch import runtime_bin_dir

    out = io.StringIO()
    try:
        global_bin_dir = harness_runtime / "rig" / "bin"
        if sink:
            sink(ComponentOutputEvent(message="[rig] updating global embedded rig binaries"))
        with contextlib.redirect_stdout(out):
            _update(target_bin_dir=global_bin_dir)
        active_bin_dir = runtime_bin_dir()
        global_active = active_bin_dir.resolve() == global_bin_dir.resolve()
        project_local_overrides_global = not global_active
        if sink and project_local_overrides_global:
            sink(
                ComponentOutputEvent(
                    message=(
                        "[rig] global binaries updated, but a project-local embedded rig "
                        "binary still takes precedence"
                    ),
                    kind="log",
                    level="warning",
                )
            )
        output = out.getvalue().strip()
        if sink and output:
            sink(ComponentOutputEvent(message=output))
        return {
            "ok": True,
            "output": output,
            "global_bin_dir": str(global_bin_dir),
            "active_bin_dir": str(active_bin_dir),
            "global_active": global_active,
            "project_local_overrides_global": project_local_overrides_global,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "output": out.getvalue().strip()}
