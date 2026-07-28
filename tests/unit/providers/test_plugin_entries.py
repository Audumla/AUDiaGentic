from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator

from audiagentic.components.providers.contracts.plugin_entry import (
    PluginEntryRequest,
    PluginEntryResult,
)
from audiagentic.components.providers.services.capabilities import plugin_entries


def test_descriptor_plugin_capability_apply_status_prune(monkeypatch, tmp_path):
    """Apply writes the entry, status detects it present, prune removes it."""
    # Use a real JSON file on disk so the name-keyed adapter works end-to-end.
    json_file = tmp_path / "plugins.json"
    json_file.write_text("{}")

    def reader(path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))

    def writer(path: Path, data: dict[str, object]) -> None:
        path.write_text(json.dumps(data), encoding="utf-8")

    def remover(path: Path, name: str) -> bool:
        current = reader(path)
        if name in current:
            del current[name]
            writer(path, current)
            return True
        return False

    spec = SimpleNamespace(
        config_path=lambda project_root: json_file,
        reader=reader,
        writer=writer,
        remover=remover,
        refresh_mode="none",
    )
    monkeypatch.setattr(
        plugin_entries,
        "get_descriptor",
        lambda _pid: SimpleNamespace(
            plugin_config=spec,
            automation_capability=lambda family_id: object()
            if family_id == "plugin-entry"
            else None,
        ),
    )

    request = PluginEntryRequest("hindsight-plugin", ownership_scope="test-scope", options=(("url", "https://memory.invalid"),))

    applied = plugin_entries.manage_plugin_entry(tmp_path, "fixture", mode="apply", request=request)
    assert applied.changed and applied.present
    assert plugin_entries.manage_plugin_entry(tmp_path, "fixture", mode="status", request=request).present
    pruned = plugin_entries.manage_plugin_entry(tmp_path, "fixture", mode="prune", request=request)
    assert pruned.changed

    # After prune, status should show absent
    status_after = plugin_entries.manage_plugin_entry(tmp_path, "fixture", mode="status", request=request)
    assert not status_after.present


def test_missing_plugin_capability_is_unsupported(monkeypatch, tmp_path):
    monkeypatch.setattr(plugin_entries, "get_descriptor", lambda _pid: None)
    result = plugin_entries.manage_plugin_entry(
        tmp_path, "fixture", mode="status", request=PluginEntryRequest("entry", ownership_scope="test")
    )
    assert not result.ok and not result.supported


def test_foreign_plugin_entries_preserved(monkeypatch, tmp_path):
    """Foreign (non-owned) entries in the plugin array survive apply/prune."""
    json_file = tmp_path / "plugins.json"
    json_file.write_text('{"foreign-pkg": {"setting": "value"}}')

    def reader(path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))

    def writer(path: Path, data: dict[str, object]) -> None:
        """Upsert entries from ``data`` into the existing config, preserving others."""
        current = reader(path)
        current.update(data)
        path.write_text(json.dumps(current), encoding="utf-8")

    def remover(path: Path, name: str) -> bool:
        current = reader(path)
        if name in current:
            del current[name]
            path.write_text(json.dumps(current), encoding="utf-8")
            return True
        return False

    spec = SimpleNamespace(
        config_path=lambda project_root: json_file,
        reader=reader,
        writer=writer,
        remover=remover,
        refresh_mode="none",
    )
    monkeypatch.setattr(
        plugin_entries,
        "get_descriptor",
        lambda _pid: SimpleNamespace(
            plugin_config=spec,
            automation_capability=lambda family_id: object()
            if family_id == "plugin-entry"
            else None,
        ),
    )

    request = PluginEntryRequest("our-plugin", ownership_scope="test-scope", options=(("url", "https://ours.invalid"),))

    applied = plugin_entries.manage_plugin_entry(tmp_path, "fixture", mode="apply", request=request)
    assert applied.changed and applied.present

    # Foreign entry should still be present
    current = reader(json_file)
    assert "foreign-pkg" in current

    # Prune our entry
    pruned = plugin_entries.manage_plugin_entry(tmp_path, "fixture", mode="prune", request=request)
    assert pruned.changed

    # Foreign entry must survive prune
    current = reader(json_file)
    assert "foreign-pkg" in current, "foreign plugin entry was destroyed by prune"


def test_serialized_contracts_match_concrete_schemas():
    contract_dir = Path(plugin_entries.__file__).resolve().parents[2] / "contracts"
    payload_schema = json.loads(
        (contract_dir / "provider-plugin-entry-payload.schema.json").read_text(
            encoding="utf-8"
        )
    )
    result_schema = json.loads(
        (contract_dir / "provider-plugin-entry-result.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(payload_schema).validate(
        PluginEntryRequest("hindsight-plugin", ownership_scope="test", options=(("url", "https://memory.invalid"),)).to_mapping()
    )
    Draft202012Validator(result_schema).validate(
        PluginEntryResult(ok=True, supported=True, provider_id="opencode").to_mapping()
    )
