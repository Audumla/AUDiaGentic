"""HM21 (descoped): hindsight MCP entry ownership + provider writer audit.

1. The hindsight entry flows through the managed ownership sync (managed id
   ``ag-hindsight``) so managed tooling sees it, collisions are detected, and
   ag-* subset syncs never disturb it.
2. Writer audit: every provider mcp_config writer must round-trip the
   URL-form hindsight entry (validate-first (a) of the original HM21).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.mcp_recipe import (
    build_hindsight_mcp_entry,
)
from audiagentic.components.memory.hindsight.recipes import (
    HINDSIGHT_MANAGED_ID,
    _McpConfigAdapter,
)
from audiagentic.foundation.mcp import McpServerEntry


def _backend() -> HindsightBackendConfig:
    return HindsightBackendConfig(base_url="http://127.0.0.1:8888", transport="http")


def _entry_to_dict(entry: McpServerEntry) -> dict:
    return {
        "url": entry.url,
        "transport": entry.transport,
        "headers": dict(entry.headers or {}),
        "command": entry.command,
    }


class _StubSpec:
    """Minimal McpConfigSpec-shaped stub over a JSON file of entries."""

    format = "json"
    refresh_mode = "file-watch"
    reload_fn = None

    def __init__(self, config_path: str) -> None:
        self.config_path = config_path

    @staticmethod
    def reader(path: Path) -> dict[str, McpServerEntry]:
        if not Path(path).exists():
            return {}
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return {
            name: McpServerEntry(
                name=name,
                command=data.get("command", ""),
                url=data.get("url", ""),
                headers=data.get("headers", {}),
                transport=data.get("transport", ""),
            )
            for name, data in raw.items()
        }

    @staticmethod
    def writer(path: Path, entries: dict[str, McpServerEntry]) -> None:
        path = Path(path)
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        for name, entry in entries.items():
            current[name] = _entry_to_dict(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current), encoding="utf-8")

    @staticmethod
    def remover(path: Path, name: str) -> bool:
        path = Path(path)
        if not path.exists():
            return False
        current = json.loads(path.read_text(encoding="utf-8"))
        if name not in current:
            return False
        del current[name]
        path.write_text(json.dumps(current), encoding="utf-8")
        return True


class _StubDescriptor:
    def __init__(self, spec: _StubSpec) -> None:
        self.mcp_config = spec
        self.display_name = "Stub"


@pytest.fixture
def stub_provider(tmp_path, monkeypatch):
    spec = _StubSpec(config_path="stub-config.json")
    descriptor = _StubDescriptor(spec)
    monkeypatch.setattr(
        "audiagentic.components.providers.services.mcp.get_descriptor",
        lambda provider_id: descriptor,
    )
    return spec, tmp_path


def _row():
    from audiagentic.components.memory.hindsight.matrix import HindsightRecipeRow
    from audiagentic.components.providers.services.recipes import ProviderRecipeKind

    return HindsightRecipeRow(
        provider_id="stub-provider",
        display_name="Stub",
        integration_type="mcp-config",
        recipe_kind=ProviderRecipeKind.MCP_CONFIG,
        source_status="verified",
        audia_action="manage_config_writes",
    )


def _adapter(spec: _StubSpec, project_root: Path) -> _McpConfigAdapter:
    backend = _backend()
    config_path = project_root / spec.config_path
    return _McpConfigAdapter(
        _row(), backend, config_path, project_root=project_root,
    )


class TestManagedOwnership:
    def test_configure_registers_ownership_and_writes_entry(self, stub_provider) -> None:
        from audiagentic.components.providers.services.managed_mcp_registry import (
            load_managed_mcp_registry,
        )

        spec, root = stub_provider
        adapter = _adapter(spec, root)

        result = adapter.configure({})

        assert result.success
        entries = spec.reader(root / spec.config_path)
        assert _backend().server_name in entries
        registry = load_managed_mcp_registry(root)
        assert registry["stub-provider"][HINDSIGHT_MANAGED_ID] == _backend().server_name

    def test_prune_removes_entry_and_ownership(self, stub_provider) -> None:
        from audiagentic.components.providers.services.managed_mcp_registry import (
            load_managed_mcp_registry,
        )

        spec, root = stub_provider
        adapter = _adapter(spec, root)
        adapter.configure({})

        result = adapter.prune({})

        assert result.success
        assert _backend().server_name not in spec.reader(root / spec.config_path)
        assert HINDSIGHT_MANAGED_ID not in load_managed_mcp_registry(root).get("stub-provider", {})

    def test_ag_subset_sync_never_touches_hindsight_entry(self, stub_provider) -> None:
        from audiagentic.components.providers.services.mcp import (
            sync_managed_provider_mcp_subset,
        )

        spec, root = stub_provider
        adapter = _adapter(spec, root)
        adapter.configure({})

        # An unrelated ag-* subset sync with empty desired state must not
        # remove hindsight's entry — subset isolation is the safety property
        # that makes shared ownership registration safe.
        sync_managed_provider_mcp_subset(
            "stub-provider", root, {}, managed_ids={"ag-lsp"}
        )

        assert _backend().server_name in spec.reader(root / spec.config_path)

    def test_provision_and_teardown_lifecycle(self, stub_provider) -> None:
        spec, root = stub_provider
        adapter = _adapter(spec, root)

        provisioned = adapter.provision({})
        assert provisioned.success, provisioned.error
        assert provisioned.state.value == "verified"

        torn_down = adapter.teardown({})
        assert torn_down.success, torn_down.error
        assert _backend().server_name not in spec.reader(root / spec.config_path)


class TestProviderWriterAudit:
    """Round-trip the URL-form hindsight entry through every provider writer."""

    def _providers_with_mcp(self):
        from audiagentic.components.providers.descriptors.registry import all_descriptors

        return {
            pid: d for pid, d in all_descriptors().items() if d.mcp_config is not None
        }

    def test_url_entry_round_trips_through_every_remote_capable_writer(self, tmp_path) -> None:
        """Providers declaring remote: true must round-trip url-form entries.

        Providers whose config format cannot express remote entries must
        declare ``remote: false`` in their mcp_config — the hindsight builder
        consults that flag instead of writing a broken entry.
        """
        entry = build_hindsight_mcp_entry(_backend())
        failures: dict[str, str] = {}
        stdio_only: set[str] = set()

        for provider_id, descriptor in self._providers_with_mcp().items():
            spec = descriptor.mcp_config
            if not spec.remote:
                stdio_only.add(provider_id)
                continue
            config_path = tmp_path / provider_id / "config-under-audit"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                spec.writer(config_path, {entry.name: entry})
                read_back = spec.reader(config_path)
            except Exception as exc:  # noqa: BLE001 - audit collects all failures
                failures[provider_id] = f"writer/reader raised: {exc}"
                continue
            stored = read_back.get(entry.name)
            if stored is None:
                failures[provider_id] = "entry missing after write"
                continue
            if getattr(stored, "url", "") != entry.url:
                failures[provider_id] = f"url lost (got {getattr(stored, 'url', '')!r})"

        assert not failures, f"URL-form MCP entry gaps by remote-capable provider: {failures}"
        # Declaration contract: exactly the known stdio-only formats opt out.
        assert stdio_only == {"codex", "goose"}, (
            f"remote:false declarations changed: {stdio_only} — update the "
            "hindsight audit and confirm the builder gate still matches"
        )


class TestGetManagedEntryStatus:
    """SL13 A1: get_managed_entry_status helper unit tests."""

    def _entry(self) -> McpServerEntry:
        return McpServerEntry(
            name="hindsight",
            url="http://127.0.0.1:8888/mcp",
            transport="http",
            headers={},
        )

    def test_no_mcp_config(self, tmp_path, monkeypatch) -> None:
        """Descriptor with no mcp_config → ok=False, reason='no mcp_config'."""
        from audiagentic.components.providers.services.mcp import (
            get_managed_entry_status,
        )

        class _DescNoMcp:
            mcp_config = None

        monkeypatch.setattr(
            "audiagentic.components.providers.services.mcp.get_descriptor",
            lambda _: _DescNoMcp(),
        )

        result = get_managed_entry_status(
            "stub", tmp_path, "hindsight", self._entry(),
        )
        assert not result["ok"]
        assert not result["present"]
        assert not result["matches"]
        assert result["reason"] == "no mcp_config"

    def test_no_descriptor(self, tmp_path, monkeypatch) -> None:
        """Unknown provider → ok=False."""
        from audiagentic.components.providers.services.mcp import (
            get_managed_entry_status,
        )

        monkeypatch.setattr(
            "audiagentic.components.providers.services.mcp.get_descriptor",
            lambda _: None,
        )

        result = get_managed_entry_status(
            "unknown", tmp_path, "hindsight", self._entry(),
        )
        assert not result["ok"]
        assert result["reason"] == "no mcp_config"

    def test_entry_absent(self, stub_provider) -> None:
        """Entry not yet written → present=False, reason='absent'."""
        from audiagentic.components.providers.services.mcp import (
            get_managed_entry_status,
        )

        spec, root = stub_provider
        # Config file does not exist yet
        result = get_managed_entry_status(
            "stub-provider", root, "hindsight", self._entry(),
        )
        assert result["ok"]
        assert not result["present"]
        assert not result["matches"]
        assert result["reason"] == "absent"

    def test_entry_matches(self, stub_provider) -> None:
        """Entry written and matching → matches=True."""
        from audiagentic.components.providers.services.mcp import (
            get_managed_entry_status,
        )

        spec, root = stub_provider
        entry = self._entry()
        # Write the entry via the spec writer
        spec.writer(root / spec.config_path, {entry.name: entry})

        result = get_managed_entry_status(
            "stub-provider", root, "hindsight", entry,
        )
        assert result["ok"]
        assert result["present"]
        assert result["matches"]
        assert result["reason"] == "match"

    def test_entry_stale(self, stub_provider) -> None:
        """Entry exists but differs → matches=False, reason='stale'."""
        from audiagentic.components.providers.services.mcp import (
            get_managed_entry_status,
        )

        spec, root = stub_provider
        stale = McpServerEntry(
            name="hindsight",
            url="http://old.example.com/mcp",
            transport="http",
            headers={},
        )
        desired = self._entry()
        spec.writer(root / spec.config_path, {"hindsight": stale})

        result = get_managed_entry_status(
            "stub-provider", root, "hindsight", desired,
        )
        assert result["ok"]
        assert result["present"]
        assert not result["matches"]
        assert result["reason"] == "stale"

    def test_reader_raises(self, tmp_path, monkeypatch) -> None:
        """Reader raises → ok=False, reason='read failed'."""
        from audiagentic.components.providers.services.mcp import (
            get_managed_entry_status,
        )

        class _BadSpec:
            format = "json"
            refresh_mode = "file-watch"
            reload_fn = None
            config_path = "bad.json"

            @staticmethod
            def reader(path):
                raise OSError("disk error")

            @staticmethod
            def writer(path, entries):
                pass

            @staticmethod
            def remover(path, name):
                return False

        monkeypatch.setattr(
            "audiagentic.components.providers.services.mcp.get_descriptor",
            lambda _: type(_, (object,), {"mcp_config": _BadSpec(), "display_name": "Bad"})(),
        )

        result = get_managed_entry_status(
            "bad", tmp_path, "hindsight", self._entry(),
        )
        assert not result["ok"]
        assert result["reason"] == "read failed"

    def test_full_entry_comparison_remote(self, stub_provider) -> None:
        """Remote entry with headers/transport compared correctly."""
        from audiagentic.components.providers.services.mcp import (
            get_managed_entry_status,
        )

        spec, root = stub_provider
        full_entry = McpServerEntry(
            name="hindsight",
            url="http://127.0.0.1:8888/mcp",
            transport="http",
            headers={"Authorization": "Bearer test"},
        )
        spec.writer(root / spec.config_path, {"hindsight": full_entry})

        result = get_managed_entry_status(
            "stub-provider", root, "hindsight", full_entry,
        )
        assert result["matches"]
