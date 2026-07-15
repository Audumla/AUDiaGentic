from __future__ import annotations

from types import SimpleNamespace

from audiagentic.components.providers.contracts.plugin_entry import PluginEntryRequest
from audiagentic.components.providers.services import plugin_entries


def test_descriptor_plugin_capability_apply_status_prune(monkeypatch, tmp_path):
    entries: dict[str, dict[str, object]] = {}
    spec = SimpleNamespace(
        config_path="plugins.json",
        reader=lambda _path, name: entries.get(name),
        writer=lambda _path, name, value: entries.__setitem__(name, value),
        remover=lambda _path, name: entries.pop(name, None) is not None,
    )
    monkeypatch.setattr(plugin_entries, "get_descriptor", lambda _pid: SimpleNamespace(plugin_config=spec))
    request = PluginEntryRequest("hindsight-plugin", (("url", "https://memory.invalid"),))

    applied = plugin_entries.manage_plugin_entry(tmp_path, "fixture", mode="apply", request=request)
    assert applied.changed and applied.present
    assert plugin_entries.manage_plugin_entry(tmp_path, "fixture", mode="status", request=request).present
    assert plugin_entries.manage_plugin_entry(tmp_path, "fixture", mode="prune", request=request).changed


def test_missing_plugin_capability_is_unsupported(monkeypatch, tmp_path):
    monkeypatch.setattr(plugin_entries, "get_descriptor", lambda _pid: None)
    result = plugin_entries.manage_plugin_entry(
        tmp_path, "fixture", mode="status", request=PluginEntryRequest("entry")
    )
    assert not result.ok and not result.supported
