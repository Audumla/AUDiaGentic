"""AgentTaskFactory and AgentTask (AS63 / RV891).

Phase 1: the object-oriented `agent_id`-primary submission shape over the
existing gateway machinery, unchanged underneath. `AgentTaskFactory` routes
through `agents_gateway_client.get_gateway_client(project_root)` -- the same mode-aware
seam (in-process/standalone/automatic, `AUDIAGENTIC_GATEWAY_MODE`) every
other gateway consumer (MCP tools, `agents_gateway_client`) already uses --
rather than importing `agents_gateway_api` directly, so it works correctly
whichever gateway mode the process is running under, not just in-process.

It does not yet extract `_QUEUE_MANAGER` out of its module-global form, so it
is not yet composed (nothing to inject -- see class docstring). That
extraction, and actually registering `AgentTaskFactory` through foundation
composition, is a separate, later phase (AS63's remaining steps 9-12) --
flagged, not silently folded in here.

`AgentTask` is a freely-constructed handle, not composed and not cached
state: every method re-reads the durable store via the same client calls
`gateway_mcp.py`'s tools already use. A consumer may hold as many
`AgentTask` objects as it likes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


class AgentTask:
    """A handle to one gateway request, resolved through an Agent Definition
    (or directly, via `AgentTaskFactory.submit_raw`).

    Thin delegating wrapper -- holds only `project_root` and `request_id`.
    Every method re-reads the durable store on each call; nothing here is
    cached, so multiple `AgentTask` instances for the same request_id (e.g.
    held by different consumers) always agree with each other and with the
    persisted record, including across process restarts.
    """

    def __init__(self, project_root: Path, request_id: str) -> None:
        self._project_root = project_root
        self._request_id = request_id

    @property
    def request_id(self) -> str:
        return self._request_id

    def status(self) -> dict[str, Any]:
        """Return the current persisted state of this task."""
        from audiagentic.components.agents.gateway.client import get_gateway_client

        return get_gateway_client(self._project_root).get_execution_request(
            self._project_root, self._request_id
        )

    def result(self) -> dict[str, Any]:
        """Alias for `status()` -- same delegating read, named for call-site
        readability once a task is known to be terminal."""
        return self.status()

    def wait(self, timeout_seconds: float | None = None) -> dict[str, Any]:
        """Block until this task reaches a terminal state or the timeout elapses."""
        from audiagentic.components.agents.gateway.client import get_gateway_client

        return get_gateway_client(self._project_root).wait_execution_request(
            self._project_root, self._request_id, timeout_seconds
        )

    def cancel(self) -> dict[str, Any]:
        """Cancel a queued task, or best-effort mark a running one cancel-requested."""
        from audiagentic.components.agents.gateway.client import get_gateway_client

        return get_gateway_client(self._project_root).cancel_execution_request(
            self._project_root, self._request_id
        )


class AgentTaskFactory:
    """Mints `AgentTask` handles. `agent_id`-based submission is primary;
    `submit_raw` (direct `execution_profile_id`) is the explicit, separately
    named lower-level surface -- not a hidden dual route.

    Phase 1: holds only `project_root`, no injected dependencies -- the
    underlying queue/session machinery is still reached through
    `get_gateway_client(project_root)`, unchanged. Composing this factory for real
    (constructor-injected queue manager/session runtime, `_QUEUE_MANAGER`
    extracted out of its module-global form) is AS63's remaining work, not
    done here. Agent Definition resolution stays a plain function call either
    way (RV890) -- it is never injected or composed.
    """

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    def submit(self, agent_id: str, *, prompt_body: str | None = None, **kwargs: Any) -> AgentTask:
        """Submit work as `agent_id`: resolves its Execution Profile and
        dispatches through the same path `submit_raw` uses.

        Raises AudiaGenticError(RES-AGD-001) if the agent definition is not found.
        """
        from audiagentic.components.agents.gateway.client import get_gateway_client
        from audiagentic.components.agents.models.agent_definition_api import (
            get_agent_definition,
        )

        definition = get_agent_definition(self._project_root, agent_id)
        record = get_gateway_client(self._project_root).submit_execution_request(
            self._project_root,
            execution_profile_id=definition["execution_profile_id"],
            prompt_body=prompt_body,
            **kwargs,
        )
        return AgentTask(self._project_root, record["request-id"])

    def submit_raw(
        self,
        execution_profile_id: str | None = None,
        *,
        prompt_body: str | None = None,
        **kwargs: Any,
    ) -> AgentTask:
        """Submit work directly against an Execution Profile, bypassing Agent
        Definition resolution. The explicit lower-level surface (RV891) --
        for operator/raw use, not the primary path."""
        from audiagentic.components.agents.gateway.client import get_gateway_client

        record = get_gateway_client(self._project_root).submit_execution_request(
            self._project_root,
            execution_profile_id=execution_profile_id,
            prompt_body=prompt_body,
            **kwargs,
        )
        return AgentTask(self._project_root, record["request-id"])

    def get(self, request_id: str) -> AgentTask:
        """Rehydrate a handle for an existing request_id -- e.g. after a
        restart, or from a reference persisted elsewhere. Does not verify the
        request exists; that surfaces on first use, the same as a fresh handle."""
        return AgentTask(self._project_root, request_id)
