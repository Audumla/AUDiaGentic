"""Tests for the generic managed-fragment reconciler (SL10).

Engine tests use a dict-backed fake store and in-memory registry — no
provider or MCP imports, proving the foundation layer is domain-opaque.
"""

from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.toolchains.config.fragments import (
    FragmentStore,
    reconcile_fragments,
)

_PATH = Path("fake-target")


class _Fake:
    """Dict-backed store + in-memory ownership registry."""

    def __init__(self, entries: dict | None = None, registry: dict | None = None) -> None:
        self.entries: dict[str, object] = dict(entries or {})
        self.registry: dict[str, dict[str, str]] = dict(registry or {})
        self.saves = 0

    def store(self) -> FragmentStore:
        return FragmentStore(
            read=lambda path: dict(self.entries),
            write=lambda path, items: self.entries.update(items),
            remove=lambda path, name: self.entries.pop(name, None) is not None,
        )

    def load(self) -> dict[str, dict[str, str]]:
        return {k: dict(v) for k, v in self.registry.items()}

    def save(self, registry: dict[str, dict[str, str]]) -> None:
        self.registry = registry
        self.saves += 1

    def reconcile(self, scope: str, desired: dict, *, managed_ids: set[str] | None = None):
        return reconcile_fragments(
            self.store(),
            _PATH,
            scope,
            desired,
            registry_load=self.load,
            registry_save=self.save,
            managed_ids=managed_ids,
        )


def test_writes_desired_and_records_ownership() -> None:
    fake = _Fake()
    result = fake.reconcile("prov", {"ag-x": ("x-server", {"url": "http://x"})})

    assert result.ok and result.changed
    assert result.updated == ["x-server"]
    assert fake.entries == {"x-server": {"url": "http://x"}}
    assert fake.registry["prov"] == {"ag-x": "x-server"}
    assert fake.saves == 1


def test_removes_stale_owned_entries_only() -> None:
    fake = _Fake(
        entries={"stale": 1, "user-entry": 2},
        registry={"prov": {"ag-old": "stale"}},
    )
    result = fake.reconcile("prov", {})

    assert result.removed == ["stale"]
    # unknown/user entries are never touched
    assert fake.entries == {"user-entry": 2}
    assert fake.registry["prov"] == {}


def test_rename_moves_ownership() -> None:
    fake = _Fake(entries={"old-name": 1}, registry={"prov": {"ag-x": "old-name"}})
    result = fake.reconcile("prov", {"ag-x": ("new-name", 1)})

    assert result.updated == ["new-name"]
    assert result.removed == ["old-name"]
    assert fake.entries == {"new-name": 1}
    assert fake.registry["prov"] == {"ag-x": "new-name"}


def test_cross_owner_name_collision_refused() -> None:
    fake = _Fake(entries={"shared": 1}, registry={"prov": {"ag-a": "shared"}})
    result = fake.reconcile("prov", {"ag-a": ("shared", 1), "ag-b": ("shared", 2)})

    assert not result.ok
    assert result.collisions and result.collisions[0]["managed_id"] == "ag-b"
    # ag-a's entry untouched by the refused write
    assert fake.entries["shared"] == 1


def test_subset_sync_touches_only_listed_ids() -> None:
    fake = _Fake(
        entries={"a-name": 1, "b-name": 2},
        registry={"prov": {"ag-a": "a-name", "ag-b": "b-name"}},
    )
    # desired omits ag-b, but subset restricts touch-set to ag-a
    result = fake.reconcile("prov", {"ag-a": ("a-name", 10)}, managed_ids={"ag-a"})

    assert result.updated == ["a-name"]
    assert "b-name" in fake.entries  # ag-b untouched
    assert fake.registry["prov"]["ag-b"] == "b-name"


def test_noop_when_nothing_desired_and_nothing_owned() -> None:
    fake = _Fake(entries={"user": 1})
    result = fake.reconcile("prov", {})
    assert result.ok and not result.changed
    assert result.updated == [] and result.removed == []


def test_scopes_are_isolated() -> None:
    fake = _Fake(
        entries={"other-scope-entry": 1},
        registry={"other": {"ag-x": "other-scope-entry"}},
    )
    result = fake.reconcile("prov", {})
    assert not result.changed
    assert fake.entries == {"other-scope-entry": 1}
    assert fake.registry["other"] == {"ag-x": "other-scope-entry"}


def test_engine_module_has_no_component_imports() -> None:
    """SL10 hard constraint: no MCP/provider binding in the generic layer."""
    import audiagentic.foundation.toolchains.config.fragments as fragments

    source = Path(fragments.__file__).read_text(encoding="utf-8")
    assert "audiagentic.components" not in source
    assert "McpServerEntry" not in source
