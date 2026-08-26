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
