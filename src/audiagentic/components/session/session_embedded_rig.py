"""Embedded rig operations for the core session component."""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
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


def embedded_rig_upgrade_status(*, scope: str) -> dict[str, Any]:
    """Return the owned recipe's local, non-mutating upgrade assessment."""
    from audiagentic.runtime.rig.embedded.launch import runtime_bin_dir
    from audiagentic.runtime.rig.embedded.recipe import llama_cpp_recipe

    if scope == "global":
        from audiagentic.foundation.paths.home import global_harness_runtime

        target = global_harness_runtime() / "rig" / "bin"
    elif scope == "local":
        target = runtime_bin_dir()
    else:
        return {"ok": False, "error": "scope must be 'local' or 'global'", "scope": scope}
    result = llama_cpp_recipe(target).upgrade_status({})
    return {
        "ok": result.success,
        "scope": scope,
        "state": result.state.value,
        "status": result.status,
        "details": result.details,
        "target_bin_dir": str(target),
    }


async def update_embedded_rig() -> dict[str, Any]:
    from audiagentic.runtime.rig.embedded.launch import runtime_bin_dir
    from audiagentic.runtime.rig.embedded.recipe import llama_cpp_recipe

    def _work(sink):
        out = io.StringIO()
        try:
            bin_dir = runtime_bin_dir()
            active_profile = active_embedded_rig_profile()
            if active_profile:
                from audiagentic.foundation.system.managed_service import ManagedServiceStore
                from audiagentic.runtime.rig.service import RIG_SERVICE_KEY

                store = ManagedServiceStore(RIG_SERVICE_KEY)
                if store.record_path.exists() and store.read().state in {
                    "starting", "running", "draining", "stopping",
                }:
                    return {
                        "ok": False,
                        "error": "embedded rig is active; release managed clients before upgrading binaries",
                        "output": "",
                    }
            if sink:
                if active_profile:
                    sink(
                        ComponentOutputEvent(
                            message=(
                                f"[rig] updating binaries for embedded rig '{active_profile}'; "
                                "the running managed service remains untouched"
                            )
                        )
                    )
                else:
                    sink(ComponentOutputEvent(message="[rig] updating embedded rig binaries"))

            with contextlib.redirect_stdout(out):
                result = llama_cpp_recipe(bin_dir).upgrade({})
            if not result.success:
                return {"ok": False, "error": result.error or result.status, "output": out.getvalue().strip()}

            if sink:
                sink(ComponentOutputEvent(message=out.getvalue().strip()))
            return {
                "ok": True,
                "output": out.getvalue().strip(),
                "restarted": False,
                "endpoint": None,
                "profile": active_profile,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "output": out.getvalue().strip()}

    return await asyncio.to_thread(_work, None)


async def update_global_embedded_rig() -> dict[str, Any]:
    from audiagentic.foundation.paths.home import global_harness_runtime

    def _work(sink):
        return _update_global_embedded_rig_impl(global_harness_runtime(), sink=sink)

    return await asyncio.to_thread(_work, None)


def _update_global_embedded_rig_impl(harness_runtime, *, sink=None) -> dict[str, Any]:
    from audiagentic.runtime.rig.embedded.launch import runtime_bin_dir
    from audiagentic.runtime.rig.embedded.recipe import llama_cpp_recipe

    out = io.StringIO()
    try:
        global_bin_dir = harness_runtime / "rig" / "bin"
        if sink:
            sink(ComponentOutputEvent(message="[rig] updating global embedded rig binaries"))
        with contextlib.redirect_stdout(out):
            result = llama_cpp_recipe(global_bin_dir).upgrade({})
        if not result.success:
            return {"ok": False, "error": result.error or result.status, "output": out.getvalue().strip()}
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
