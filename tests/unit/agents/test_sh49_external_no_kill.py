"""SH49: gateway cleanup never terminates an EXTERNAL session's process.

``attach_binding`` (the only EXTERNAL binding) has no runtime caller yet, so
these sentinel tests open a session normally and mark its handle EXTERNAL,
then drive the real cleanup paths: client close, transport failure and
runtime shutdown. ``close()`` (which terminates a gateway-owned child) must
never run for EXTERNAL; ``detach()`` must. OWNED behaviour is unchanged.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from tests.unit.agents.test_agents_gateway_sessions import (
    FakeAgentSessionTransport,
    _build_fake_prepared,
    _Clock,
)

from audiagentic.components.agents.gateway.session import sessions_store as session_store
from audiagentic.components.agents.gateway.session.sessions import SessionRuntime, _binding_ownership
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.transports.session_binding import SessionOwnership


class SentinelTransport(FakeAgentSessionTransport):
    """Records every destructive and non-destructive cleanup attempt."""

    def __init__(self, *, can_detach: bool = True) -> None:
        super().__init__()
        self.calls: list[str] = []
        if can_detach:
            self.detach = self._detach

    async def close(self) -> None:
        self.calls.append("close")
        await super().close()

    async def _detach(self) -> None:
        self.calls.append("detach")


@pytest.fixture
def rig(tmp_path: Path):
    transports: list[SentinelTransport] = []
    options: dict[str, Any] = {"can_detach": True}

    def prepare(project_root, *, provider_id, surface_hint, model_id=None, **kwargs):
        transport = SentinelTransport(can_detach=options["can_detach"])
        transport.ag_session_id = kwargs["ag_session_id"]
        transports.append(transport)
        return _build_fake_prepared(transport)

    runtime = SessionRuntime(clock=_Clock(), reap_interval_seconds=60, provider_prepare_fn=prepare)
    yield runtime, transports, options, tmp_path
    runtime.shutdown()


def _open(runtime: SessionRuntime, root: Path, *, external: bool) -> str:
    record = runtime.open_session(root, execution_profile_id="profile-1", provider_id="opencode", model_id="m1",
                                  surface_hint=None)
    session_id = record["session-id"]
    if external:
        runtime._handles[session_id].ownership = SessionOwnership.EXTERNAL
    return session_id


@pytest.mark.parametrize(
    ("binding", "expected"),
    [
        (None, SessionOwnership.OWNED),
        ({"ownership": "owned"}, SessionOwnership.OWNED),
        ({"ownership": "external"}, SessionOwnership.EXTERNAL),
        ({"ownership": "something-new"}, SessionOwnership.EXTERNAL),  # unknown fails closed
        ({}, SessionOwnership.OWNED),
    ],
)
def test_binding_ownership(binding, expected) -> None:
    record = {} if binding is None else {"binding": binding}
    assert _binding_ownership(record) is expected


def test_owned_session_is_closed_as_before(rig) -> None:
    runtime, transports, _, root = rig
    session_id = _open(runtime, root, external=False)
    runtime.close_session(root, session_id)
    assert transports[0].calls == ["close"]


def test_external_client_close_detaches_and_never_closes(rig) -> None:
    runtime, transports, _, root = rig
    session_id = _open(runtime, root, external=True)
    runtime.close_session(root, session_id)
    assert transports[0].calls == ["detach"]
    assert session_store.read_session_record(root, session_id)["state"] == "closed"


def test_external_transport_failure_detaches_and_never_closes(rig) -> None:
    runtime, transports, _, root = rig
    session_id = _open(runtime, root, external=True)
    transports[0].alive = False
    with pytest.raises(AudiaGenticError, match="RES-AGW-003"):
        runtime.prompt_in_session(root, session_id, "after the native side went away")
    assert "close" not in transports[0].calls
    assert transports[0].calls == ["detach"]
    assert session_store.read_session_record(root, session_id)["state"] == "failed"


def test_external_runtime_shutdown_detaches_and_never_closes(rig) -> None:
    runtime, transports, _, root = rig
    _open(runtime, root, external=True)
    runtime.shutdown()
    deadline = time.monotonic() + 2
    while not transports[0].calls and time.monotonic() < deadline:
        time.sleep(0.02)
    assert transports[0].calls == ["detach"]


def test_external_without_detach_is_left_running(rig) -> None:
    runtime, transports, options, root = rig
    options["can_detach"] = False
    session_id = _open(runtime, root, external=True)
    runtime.close_session(root, session_id)
    assert transports[0].calls == []  # fail closed: no detach possible, still never close
