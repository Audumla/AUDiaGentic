from pathlib import Path

from audiagentic.components.agents.gateway.queue.watchdog_registry import WatchdogRequestRegistry


def test_watchdog_registry_scopes_records_by_project_and_request(tmp_path: Path) -> None:
    registry = WatchdogRequestRegistry()
    project_a = tmp_path / "a"
    project_b = tmp_path / "b"
    registry.register(project_a, {"request-id": "req-1", "state": "running"})
    registry.register(project_b, {"request-id": "req-1", "state": "running"})

    snapshot = registry.snapshot()

    assert {(root.name, record["request-id"]) for root, record in snapshot} == {("a", "req-1"), ("b", "req-1")}
    registry.unregister(project_a, "req-1")
    assert len(registry.snapshot()) == 1


def test_watchdog_registry_diagnose_pass_is_scoped_and_cleans_terminal(tmp_path: Path) -> None:
    registry = WatchdogRequestRegistry()
    project_a = tmp_path / "a"
    project_b = tmp_path / "b"
    registry.register(project_a, {"request-id": "req-1", "state": "running"})
    registry.register(project_b, {"request-id": "req-1", "state": "running"})

    seen: list[Path] = []

    def diagnose(root: Path, record: dict) -> dict:
        seen.append(root)
        updated = dict(record)
        if root == project_a:
            updated["state"] = "failed"
        return updated

    results = registry.diagnose(diagnose)

    assert len(results) == 2
    assert set(seen) == {project_a.resolve(), project_b.resolve()}
    assert registry.snapshot() == ((project_b.resolve(), {"request-id": "req-1", "state": "running"}),)


def test_host_watchdog_reconciles_stale_transport_without_replaying_prompt(
    tmp_path: Path, monkeypatch
) -> None:
    """A stale lease triggers transport revalidation and only a reconcile record."""
    from audiagentic.components.agents.gateway.service.host import GatewayServiceHost

    project_root = tmp_path / "project"
    project_root.mkdir()
    request_id = "req-stale"
    initial = {
        "request-id": request_id,
        "state": "running",
        "session-id": "ses-1",
        "revision": 7,
        "watchdog-state": "active",
    }
    diagnosed = {
        **initial,
        "watchdog-state": "intervention",
        "diagnostics": {"resolution-state": "unresolved", "reason": "stale-progress"},
    }
    persisted = {**diagnosed, "diagnostics": {"resolution-state": "reconciled"}}

    class Registry:
        def __init__(self) -> None:
            self.current = (project_root.resolve(), dict(initial))
            self.updates: list[dict] = []

        def snapshot(self):
            return ((self.current[0], dict(self.current[1])),)

        def update(self, root, record):
            self.current = (root.resolve(), dict(record))
            self.updates.append(dict(record))

        def unregister(self, *_args):
            raise AssertionError("a non-terminal reconcile must remain registered")

    class Runtime:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def reconcile_active_transport(self, session_id: str, req_id: str):
            self.calls.append((session_id, req_id))
            return {"status": "reconciled", "session-id": session_id}

    registry = Registry()
    runtime = Runtime()
    recovered: list[dict] = []

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.watchdog_registry.watchdog_registry",
        lambda: registry,
    )
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.dispatch.diagnose_activity_lease",
        lambda _root, _record: dict(diagnosed),
    )
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.session.sessions.peek_session_runtime",
        lambda: runtime,
    )
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.api.recover_execution_request",
        lambda root, req_id, **kwargs: recovered.append(
            {"root": root, "request-id": req_id, **kwargs}
        ),
    )
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.store.read_record",
        lambda _root, _req_id: dict(persisted),
    )

    result = GatewayServiceHost.run_watchdog_pass(object.__new__(GatewayServiceHost))

    assert runtime.calls == [("ses-1", request_id)]
    assert recovered == [
        {
            "root": project_root.resolve(),
            "request-id": request_id,
            "action": "reconcile",
            "expected_revision": 7,
        }
    ]
    assert result == (persisted,)
    assert registry.updates[-1] == persisted


def test_host_watchdog_retries_operator_requested_reconciliation(
    tmp_path: Path, monkeypatch
) -> None:
    """An operator reconcile intent must not suppress the next watchdog pass."""
    from audiagentic.components.agents.gateway.service.host import GatewayServiceHost

    project_root = tmp_path / "project"
    project_root.mkdir()
    request_id = "req-reconcile-requested"
    diagnosed = {
        "request-id": request_id,
        "state": "running",
        "session-id": "ses-1",
        "revision": 8,
        "watchdog-state": "intervention",
        "diagnostics": {
            "resolution-state": "reconciliation-requested",
            "reason": "stale-progress",
        },
    }

    class Registry:
        def __init__(self) -> None:
            self.current = (project_root.resolve(), dict(diagnosed))

        def snapshot(self):
            return ((self.current[0], dict(self.current[1])),)

        def update(self, root, record):
            self.current = (root.resolve(), dict(record))

        def unregister(self, *_args):
            raise AssertionError("a non-terminal reconcile must remain registered")

    class Runtime:
        def reconcile_active_transport(self, session_id: str, req_id: str):
            assert (session_id, req_id) == ("ses-1", request_id)
            return {"status": "reconciled"}

    registry = Registry()
    recovered: list[dict] = []
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.watchdog_registry.watchdog_registry",
        lambda: registry,
    )
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.dispatch.diagnose_activity_lease",
        lambda _root, _record: dict(diagnosed),
    )
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.session.sessions.peek_session_runtime",
        lambda: Runtime(),
    )
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.api.recover_execution_request",
        lambda root, req_id, **kwargs: recovered.append(
            {"root": root, "request-id": req_id, **kwargs}
        ),
    )
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.store.read_record",
        lambda _root, _req_id: dict(diagnosed),
    )

    result = GatewayServiceHost.run_watchdog_pass(object.__new__(GatewayServiceHost))

    assert recovered == [
        {
            "root": project_root.resolve(),
            "request-id": request_id,
            "action": "reconcile",
            "expected_revision": 8,
        }
    ]
    assert result == (diagnosed,)


def test_host_watchdog_orphan_retirement_aborts_on_revision_race(
    tmp_path: Path, monkeypatch
) -> None:
    """A binding/revision race must not terminalize the request or session."""
    from datetime import datetime, timedelta, timezone

    from audiagentic.foundation.contracts.errors import AudiaGenticError
    from audiagentic.components.agents.gateway.service.host import GatewayServiceHost

    project_root = tmp_path / "project"
    project_root.mkdir()
    request_id = "req-orphan-race"
    diagnosed = {
        "request-id": request_id,
        "state": "running",
        "session-id": "ses-race",
        "revision": 11,
        "updated-at": (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat(),
        "watchdog-state": "intervention",
        "watchdog-reason": "initial-activity-observation-expired",
        "watchdog-policy": {"diagnostic-grace-seconds": 1},
        "diagnostics": {"resolution-state": "unresolved"},
        "dispatch-owner-epoch": "owner-1",
        "worker-id": "worker-1",
        "attempt-epoch": 1,
    }

    class Registry:
        def __init__(self) -> None:
            self.current = (project_root.resolve(), dict(diagnosed))

        def snapshot(self):
            return ((self.current[0], dict(self.current[1])),)

        def update(self, root, record):
            self.current = (root.resolve(), dict(record))

        def unregister(self, *_args):
            raise AssertionError("the raced request must remain registered")

    class Runtime:
        def session_runtime_status(self, session_id: str):
            assert session_id == "ses-race"
            return {"available": False}

        def reconcile_active_transport(self, session_id: str, req_id: str):
            assert (session_id, req_id) == ("ses-race", "req-orphan-race")
            return {"status": "unavailable"}

    terminal_call: dict = {}
    session_terminalized = False

    def raced_terminal(*_args, **kwargs):
        terminal_call.update(kwargs)
        raise AudiaGenticError(
            code="CON-AGW-071",
            kind="agents",
            message="gateway request revision changed",
            details={"expected": 11, "actual": 12},
        )

    def fail_session_transition(*_args, **_kwargs):
        nonlocal session_terminalized
        session_terminalized = True

    registry = Registry()
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.watchdog_registry.watchdog_registry",
        lambda: registry,
    )
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.dispatch.diagnose_activity_lease",
        lambda _root, _record: dict(diagnosed),
    )
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.session.sessions.peek_session_runtime",
        lambda: Runtime(),
    )
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.session.sessions_store.read_session_record",
        lambda _root, _session_id: {"state": "active", "binding": None},
    )
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.session.sessions_store.session_provider_metadata",
        lambda _session: {},
    )
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.store.transition_owned_terminal",
        raced_terminal,
    )
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.session.sessions_store.transition_session_record",
        fail_session_transition,
    )
    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.store.read_record",
        lambda _root, _request_id: {**diagnosed, "revision": 12, "state": "running"},
    )

    result = GatewayServiceHost.run_watchdog_pass(object.__new__(GatewayServiceHost))

    assert terminal_call["expected_revision"] == 11
    assert result[0]["state"] == "running"
    assert result[0]["revision"] == 12
    assert session_terminalized is False
