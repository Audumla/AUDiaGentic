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
