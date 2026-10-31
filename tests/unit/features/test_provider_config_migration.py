"""Provider option files, the registry and the policy file move into settings, with a rollback."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from audiagentic.foundation.features import observations
from audiagentic.foundation.features.migration import (
    PROVIDER_FILES_DIR,
    PROVIDER_POLICY,
    PROVIDER_REGISTRY,
    apply_provider_config_migration,
    plan_provider_config_migration,
    rollback_provider_config_migration,
)


@pytest.fixture(autouse=True)
def _isolated_user_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("_AUDIAGENTIC_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    return root


def _write(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _settings(project: Path) -> dict:
    path = project / ".audiagentic" / "settings.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _legacy(project: Path) -> list[Path]:
    return [
        _write(project / PROVIDER_REGISTRY, {"contract-version": "v1", "providers": {
            "codex": {"install-mode": "x", "access-mode": "cli", "enabled": True, "default-model": "old", "timeout-seconds": 30},
        }}),
        _write(project / PROVIDER_FILES_DIR / "codex.yaml", {
            "install-mode": "x", "access-mode": "cli", "default-model": "gpt-5", "settings": {"a": {"b": 1}},
        }),
        _write(project / PROVIDER_POLICY, {"contract-version": "v1", "reconciliation-policy": {
            "mode": "allowlist", "allowed-providers": ["codex"], "decided-providers": ["codex", "claude"],
        }}),
    ]


def test_plan_merges_registry_and_file_and_drops_descriptor_facts(project: Path) -> None:
    _legacy(project)
    plan = plan_provider_config_migration(project)
    assert plan.patch("project") == {
        "providers": {"codex": {"default-model": "gpt-5", "timeout-seconds": 30, "settings": {"a": {"b": 1}}}},
        "reconciliation": {"mode": "allowlist", "allowed-providers": ["codex"]},
    }
    assert plan.decided == ["claude", "codex"]
    assert plan.conflicts == {}


def test_apply_writes_settings_removes_sources_and_records_decisions(project: Path) -> None:
    sources = _legacy(project)
    result = apply_provider_config_migration(project)
    assert result["status"] == "applied"
    assert not any(p.exists() for p in sources)
    assert _settings(project)["providers"]["codex"]["default-model"] == "gpt-5"
    assert observations.get_observation(project, "providers", "reconciliation.decided") == ["claude", "codex"]
    assert apply_provider_config_migration(project) == {"status": "nothing-to-migrate"}


def test_conflict_with_existing_settings_refuses_and_touches_nothing(project: Path) -> None:
    sources = _legacy(project)
    _write(project / ".audiagentic" / "settings.yaml", {"schema_version": 1, "providers": {"codex": {"default-model": "mine"}}})
    before = [p.read_bytes() for p in sources]
    with pytest.raises(ValueError, match="refused"):
        apply_provider_config_migration(project)
    assert [p.read_bytes() for p in sources] == before
    assert _settings(project)["providers"]["codex"]["default-model"] == "mine"


def test_rollback_restores_sources_and_removes_only_migrated_keys(project: Path) -> None:
    sources = _legacy(project)
    originals = [p.read_bytes() for p in sources]
    manifest = Path(apply_provider_config_migration(project)["manifest"])
    assert json.loads(manifest.read_text())["status"] == "applied"
    report = rollback_provider_config_migration(project, manifest)
    assert report["kept"] == []
    assert [p.read_bytes() for p in sources] == originals
    assert "providers" not in _settings(project) and "reconciliation" not in _settings(project)
    assert observations.get_observation(project, "providers", "reconciliation.decided") is None
    assert rollback_provider_config_migration(project, manifest) == {"restored": [], "kept": []}


def test_rollback_keeps_values_changed_after_the_migration(project: Path) -> None:
    _legacy(project)
    manifest = Path(apply_provider_config_migration(project)["manifest"])
    from audiagentic.foundation.config.writer import write_settings_patch

    write_settings_patch("project", {"providers": {"codex": {"default-model": "edited"}}}, project_root=project)
    report = rollback_provider_config_migration(project, manifest)
    assert "project.providers.codex.default-model" in report["kept"]
    assert _settings(project)["providers"]["codex"]["default-model"] == "edited"


def _source(url: str) -> dict:
    return {"source-class": "local-endpoint", "connector": "openai-compatible", "base-url": url, "model-id": "m"}


def test_model_sources_files_move_to_their_scopes_and_roll_back(project: Path, tmp_path: Path) -> None:
    project_file = _write(project / ".audiagentic" / "config" / "model-sources.yaml",
                          {"contract-version": "v1", "sources": {"p1": _source("http://p")}})
    user_file = _write(tmp_path / "home" / "config" / "model-sources.yaml",
                       {"contract-version": "v1", "sources": {"u1": _source("http://u")}})
    originals = [project_file.read_bytes(), user_file.read_bytes()]
    manifest = Path(apply_provider_config_migration(project)["manifest"])

    assert not project_file.exists() and not user_file.exists()
    assert _settings(project)["model-sources"]["p1"]["base-url"] == "http://p"
    user_settings = yaml.safe_load((tmp_path / "xdg-config" / "audiagentic" / "settings.yaml").read_text())
    assert user_settings["model-sources"]["u1"]["base-url"] == "http://u"

    report = rollback_provider_config_migration(project, manifest)
    assert report["kept"] == []
    assert [project_file.read_bytes(), user_file.read_bytes()] == originals
    assert "model-sources" not in _settings(project)
    assert "model-sources" not in yaml.safe_load((tmp_path / "xdg-config" / "audiagentic" / "settings.yaml").read_text())


def test_harness_files_move_into_the_harness_section_and_roll_back(project: Path, tmp_path: Path) -> None:
    ag = _write(project / ".audiagentic" / "config" / "harness" / "ag.yaml", {
        "harness": {"type": "pi"}, "endpoint": {"url": "http://e/v1", "model": "m", "provider": "p"},
        "mcp": {"enabled": False},
    })
    pi = _write(tmp_path / "home" / "config" / "harness" / "pi.yaml", {"tools": {"mode": "full"}})
    originals = [ag.read_bytes(), pi.read_bytes()]
    manifest = Path(apply_provider_config_migration(project)["manifest"])

    harness = _settings(project)["harness"]
    assert harness["type"] == "pi" and harness["endpoint"]["url"] == "http://e/v1" and harness["mcp"] == {"enabled": False}
    user = yaml.safe_load((tmp_path / "xdg-config" / "audiagentic" / "settings.yaml").read_text())
    assert user["harness"]["pi"]["tools"]["mode"] == "full"
    from audiagentic.foundation.config.harness_settings import harness_ag_config, harness_pi_config

    assert harness_ag_config(project)["endpoint"]["model"] == "m"
    assert harness_pi_config(project)["tools"]["mode"] == "full"

    report = rollback_provider_config_migration(project, manifest)
    assert report["kept"] == []
    assert [ag.read_bytes(), pi.read_bytes()] == originals
    assert "harness" not in _settings(project)


def test_a_legacy_harness_key_without_a_home_refuses_the_migration(project: Path) -> None:
    ag = _write(project / ".audiagentic" / "config" / "harness" / "ag.yaml", {"rig": {"port": 1}, "endpoint": {"url": "http://e/v1"}})
    plan = plan_provider_config_migration(project)
    assert any("rig" in item for item in plan.unknown)
    with pytest.raises(ValueError, match="refused"):
        apply_provider_config_migration(project)
    assert ag.exists()


def test_logging_files_move_to_their_scopes_and_roll_back(project: Path, tmp_path: Path) -> None:
    project_file = _write(project / ".audiagentic" / "config" / "foundation" / "logging.yaml",
                          {"logging": {"level": "DEBUG", "silenced": ["noisy"]}})
    local_file = _write(project / ".audiagentic" / "config" / "foundation" / "logging.local.yaml",
                        {"logging": {"format": "dev", "dir": None}})
    user_file = _write(tmp_path / "home" / "config" / "foundation" / "logging.yaml",
                       {"logging": {"console": False}})
    originals = [p.read_bytes() for p in (project_file, local_file, user_file)]
    manifest = Path(apply_provider_config_migration(project)["manifest"])

    assert _settings(project)["logging"] == {"level": "DEBUG", "silenced": ["noisy"]}
    user = yaml.safe_load((tmp_path / "xdg-config" / "audiagentic" / "settings.yaml").read_text())
    assert user["logging"] == {"format": "dev", "console": False}

    report = rollback_provider_config_migration(project, manifest)
    assert report["kept"] == []
    assert [p.read_bytes() for p in (project_file, local_file, user_file)] == originals
    assert "logging" not in _settings(project)


def test_logging_files_that_disagree_refuse_the_migration(project: Path, tmp_path: Path) -> None:
    _write(project / ".audiagentic" / "config" / "foundation" / "logging.local.yaml", {"logging": {"level": "DEBUG"}})
    _write(tmp_path / "home" / "config" / "foundation" / "logging.yaml", {"logging": {"level": "ERROR"}})
    assert any("level" in item for item in plan_provider_config_migration(project).unknown)
    with pytest.raises(ValueError, match="refused"):
        apply_provider_config_migration(project)


def test_event_config_triggers_and_prompt_syntax_files_move_and_roll_back(project: Path) -> None:
    events = _write(project / ".audiagentic" / "event" / "config.yaml", {"runtime": {"event_store": {"enabled": False}}})
    triggers = _write(project / ".audiagentic" / "config" / "agent-jobs" / "event-triggers.yaml",
                      {"triggers": [{"contract-version": "v1", "trigger-id": "t1", "kind": "event"}]})
    syntax = _write(project / ".audiagentic" / "config" / "execution" / "prompt-syntax.yaml",
                    {"contract-version": "v1", "default-profile": "compact", "profiles": {"compact": {}}})
    originals = [p.read_bytes() for p in (events, triggers, syntax)]
    manifest = Path(apply_provider_config_migration(project)["manifest"])

    settings = _settings(project)
    assert settings["events"] == {"event_store": {"enabled": False}}
    assert settings["event-triggers"][0]["trigger-id"] == "t1"
    assert settings["prompt-syntax"] == {"default-profile": "compact", "profiles": {"compact": {}}}

    report = rollback_provider_config_migration(project, manifest)
    assert report["kept"] == []
    assert [p.read_bytes() for p in (events, triggers, syntax)] == originals
    assert not ({"events", "event-triggers", "prompt-syntax"} & set(_settings(project)))


def test_project_file_moves_identity_prompt_launch_and_bindings_and_rolls_back(project: Path) -> None:
    legacy = _write(project / ".audiagentic" / "config" / "project.yaml", {
        "contract-version": "v1", "project-id": "demo", "project-name": "Demo",
        "workflow-profile": "standard", "tracked-docs-root": "docs", "runtime-root": ".audiagentic/runtime",
        "release-strategy": "semver",
        "prompt-launch": {"syntax": "prefix-token-v1", "allow-adhoc-target": True},
        "mcp-onboarding": {"contract-version": "v1", "bindings": {"ag-planning": ["pi"]}},
    })
    original = legacy.read_bytes()
    manifest = Path(apply_provider_config_migration(project)["manifest"])

    settings = _settings(project)
    assert settings["project"] == {"id": "demo", "name": "Demo"}
    assert settings["prompt-launch"] == {"allow-adhoc-target": True}
    assert settings["mcp-onboarding"] == {"bindings": {"ag-planning": ["pi"]}}
    assert not legacy.exists()

    report = rollback_provider_config_migration(project, manifest)
    assert report["kept"] == []
    assert legacy.read_bytes() == original
    assert not ({"project", "prompt-launch", "mcp-onboarding"} & set(_settings(project)))


def test_an_unfilled_project_file_migrates_to_nothing_and_is_removed(project: Path) -> None:
    legacy = _write(project / ".audiagentic" / "config" / "project.yaml", {
        "contract-version": "v1", "project-id": None, "project-name": None, "workflow-profile": "standard",
        "mcp-onboarding": {"contract-version": "v1", "bindings": {}},
    })
    apply_provider_config_migration(project)
    assert not legacy.exists()
    assert "project" not in _settings(project)


def test_a_project_file_key_without_a_home_refuses_the_migration(project: Path) -> None:
    _write(project / ".audiagentic" / "config" / "project.yaml", {"contract-version": "v1", "surprise": 1})
    assert plan_provider_config_migration(project).unknown


def test_machine_provider_override_moves_to_user_settings_and_rolls_back(project: Path, tmp_path: Path) -> None:
    override = _write(tmp_path / "home" / "config" / "providers" / "gpt-auto.yaml",
                      {"settings": {"contract-version": "v1", "turn": {"response-timeout-seconds": 42}}})
    original = override.read_bytes()
    manifest = Path(apply_provider_config_migration(project)["manifest"])

    user = yaml.safe_load((tmp_path / "xdg-config" / "audiagentic" / "settings.yaml").read_text())
    assert user["providers"]["gpt-auto"]["settings"]["turn"]["response-timeout-seconds"] == 42
    assert not override.exists()

    report = rollback_provider_config_migration(project, manifest)
    assert report["kept"] == []
    assert override.read_bytes() == original
    assert "providers" not in yaml.safe_load((tmp_path / "xdg-config" / "audiagentic" / "settings.yaml").read_text())


def test_feature_state_shards_move_to_the_user_project_scope_and_roll_back(project: Path, tmp_path: Path) -> None:
    providers = _write(project / ".audiagentic" / "config" / "runtime" / "features" / "providers.yaml", {
        "implementations": {"claude": {"enabled": True, "options": {"x": 1}}}})
    lsp = _write(project / ".audiagentic" / "config" / "runtime" / "features" / "coding_lsp.yaml", {
        "options": {"max": 5}, "features": {"language:python": {"enabled": True}},
        "implementations": {"pyright": {"enabled": False, "features": {"language:go": {"enabled": True}}}}})
    originals = [providers.read_bytes(), lsp.read_bytes()]
    plan = plan_provider_config_migration(project)
    assert plan.observations == {("providers", "enabled:claude"): True, ("coding_lsp", "enabled:pyright"): False}

    manifest = Path(apply_provider_config_migration(project)["manifest"])

    from audiagentic.foundation.features import observations
    from audiagentic.foundation.features.state import get_component_state

    assert not providers.exists() and not lsp.exists()
    assert observations.get_observation(project, "providers", "enabled:claude") is True
    state = get_component_state(project, "coding_lsp")
    assert state["options"] == {"max": 5}
    assert state["features"]["language:python"]["enabled"] is True
    assert state["implementations"]["pyright"] == {"enabled": False, "features": {"language:go": {"enabled": True}}}
    assert "features" not in _settings(project)  # the tracked project file is untouched

    report = rollback_provider_config_migration(project, manifest)
    assert report["kept"] == []
    assert [providers.read_bytes(), lsp.read_bytes()] == originals
    assert observations.observed_keys(project, "providers", "enabled:") == []
    assert get_component_state(project, "coding_lsp") == {}


def test_shard_with_an_unknown_key_refuses_the_migration(project: Path) -> None:
    shard = _write(project / ".audiagentic" / "config" / "runtime" / "features" / "agents.yaml", {"surprise": 1})
    assert any("surprise" in item for item in plan_provider_config_migration(project).unknown)
    with pytest.raises(ValueError, match="refused"):
        apply_provider_config_migration(project)
    assert shard.exists()


def test_a_shard_flag_that_disagrees_with_an_observation_is_a_conflict(project: Path) -> None:
    from audiagentic.foundation.features import observations

    _write(project / ".audiagentic" / "config" / "runtime" / "features" / "providers.yaml",
           {"implementations": {"claude": {"enabled": True}}})
    observations.record_observation(project, "providers", "enabled:claude", False, source="test")
    assert ("observation", "providers", "enabled:claude") in plan_provider_config_migration(project).conflicts


def test_config_migrate_command_previews_applies_and_rolls_back(project: Path, capsys) -> None:
    import argparse

    from audiagentic.commands.settings import run_settings_command

    shard = _write(project / ".audiagentic" / "config" / "runtime" / "features" / "providers.yaml",
                   {"implementations": {"claude": {"enabled": True, "options": {"x": 1}}}})

    def run(**kw) -> dict:
        options = {"apply": False, "rollback": None, **kw}
        args = argparse.Namespace(config_cmd="migrate", project=project, config_file=None, as_json=True, **options)
        assert run_settings_command(args) == 0
        return json.loads(capsys.readouterr().out)

    preview = run()
    assert preview["applied"] is False and preview["local-state"] == 1 and preview["settings"] == 1
    assert shard.exists()
    applied = run(apply=True)
    assert applied["applied"] is True and not shard.exists()
    undone = run(rollback=applied["manifest"])
    assert undone["kept"] == [] and shard.exists()
