from __future__ import annotations

import json

import pytest

from audiagentic.foundation.toolchains.config_patcher import ConfigPatcher
from audiagentic.foundation.toolchains.config_reader import UNSET, load_config


def test_set_key_creates_deep_path_in_empty_file(tmp_path):
    cfg = tmp_path / "settings.json"
    patcher = ConfigPatcher(cfg)

    change = patcher.set_key(("a", "b", "c"), 42)

    assert load_config(cfg) == {"a": {"b": {"c": 42}}}
    assert change.operation == "set"
    assert change.existed is False
    assert change.artifact_id.endswith("::a.b.c")


def test_set_key_records_prior_value_for_overwrite(tmp_path):
    cfg = tmp_path / "settings.json"
    cfg.write_text(json.dumps({"a": {"b": 1}}), encoding="utf-8")
    patcher = ConfigPatcher(cfg)

    change = patcher.set_key(("a", "b"), 2)

    assert change.existed is True
    assert change.prior_value == 1
    assert load_config(cfg)["a"]["b"] == 2


def test_remove_key_prunes_empty_parents(tmp_path):
    cfg = tmp_path / "settings.yaml"
    cfg.write_text("a:\n  b:\n    c: 1\n", encoding="utf-8")
    patcher = ConfigPatcher(cfg)

    change = patcher.remove_key(("a", "b", "c"))

    assert change.existed is True
    assert load_config(cfg) == {}


def test_remove_missing_key_is_reported_not_raised(tmp_path):
    cfg = tmp_path / "settings.json"
    cfg.write_text(json.dumps({"keep": True}), encoding="utf-8")
    patcher = ConfigPatcher(cfg)

    change = patcher.remove_key(("absent", "leaf"))

    assert change.existed is False
    assert load_config(cfg) == {"keep": True}


def test_mcp_entry_add_and_remove_roundtrip(tmp_path):
    cfg = tmp_path / "mcp.json"
    patcher = ConfigPatcher(cfg)

    patcher.add_mcp_entry("hindsight", {"command": "hindsight", "args": ["serve"]})
    assert load_config(cfg)["mcpServers"]["hindsight"]["command"] == "hindsight"

    patcher.remove_mcp_entry("hindsight")
    assert "mcpServers" not in load_config(cfg)


def test_add_mcp_entry_dedups_on_name(tmp_path):
    cfg = tmp_path / "mcp.json"
    patcher = ConfigPatcher(cfg)
    patcher.add_mcp_entry("x", {"v": 1})
    patcher.add_mcp_entry("x", {"v": 2})
    assert load_config(cfg)["mcpServers"] == {"x": {"v": 2}}


def test_revert_set_removes_when_new_key(tmp_path):
    cfg = tmp_path / "settings.json"
    patcher = ConfigPatcher(cfg)
    change = patcher.set_key(("new",), "v")
    patcher.revert(change)
    assert load_config(cfg) == {}


def test_revert_set_restores_prior(tmp_path):
    cfg = tmp_path / "settings.json"
    cfg.write_text(json.dumps({"k": "old"}), encoding="utf-8")
    patcher = ConfigPatcher(cfg)
    change = patcher.set_key(("k",), "new")
    patcher.revert(change)
    assert load_config(cfg)["k"] == "old"


def test_empty_key_path_rejected(tmp_path):
    patcher = ConfigPatcher(tmp_path / "x.json")
    with pytest.raises(ValueError):
        patcher.set_key((), 1)


def test_prior_value_unset_for_brand_new_key(tmp_path):
    patcher = ConfigPatcher(tmp_path / "x.json")
    change = patcher.set_key(("a",), 1)
    assert change.prior_value is UNSET
