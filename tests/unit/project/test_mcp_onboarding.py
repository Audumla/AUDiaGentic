"""Owner API/CLI/protocol proofs in disposable projects; no real harness writes."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import validate

from audiagentic.components.project import project_api as project
from audiagentic.components.providers import providers_api as providers
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIAGENTIC_REPO_ROOT", str(tmp_path))
    monkeypatch.delenv("AUDIAGENTIC_COMPONENT_PROFILE", raising=False)
    return tmp_path


@pytest.mark.parametrize("targets", [["pi"], ["opencode", "pi"]])
def test_project_recovers_native_publication_before_ownership_commit(root, monkeypatch, targets):
    from audiagentic.components.providers.services.mcp.managed_mcp_registry import (
        McpOwnershipRegistry,
    )

    original = McpOwnershipRegistry.write_document

    def crash(self, data):
        if not data.get("prepared") and "pi/component-mcp" in self.document().get("prepared", {}):
            raise OSError("after native publication")
        return original(self, data)

    monkeypatch.setattr(McpOwnershipRegistry, "write_document", crash)
    first = project.install_mcp(root, mcp_id="ag-planning", harness_ids=targets)
    assert not first["ok"] and first["phase"] == "needs_reconciliation"
    paths = [root / ".pi/mcp.json"]
    if "opencode" in targets:
        paths.append(root / ".opencode/opencode.json")
    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
    monkeypatch.setattr(McpOwnershipRegistry, "write_document", original)
    repeat = project.install_mcp(root, mcp_id="ag-planning", harness_ids=targets)
    assert repeat["ok"] and repeat["operation_id"] == first["operation_id"]
    assert all(target["configured"] for target in repeat["targets"])
    assert before == [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]


def test_conflicting_dual_ownership_authorities_are_not_guessed(root):
    from audiagentic.components.providers.services.mcp.managed_mcp_registry import (
        McpOwnershipRegistry,
    )
    from audiagentic.foundation.io import atomic_write_json

    registry = McpOwnershipRegistry(root)
    atomic_write_json(
        registry.legacy_path, {"contract-version": "v1", "providers": {"pi": {"one": "old"}}}
    )
    atomic_write_json(
        registry.path,
        {"contract-version": "v2", "providers": {"pi/component-mcp": {"two": "new"}}, "proofs": {}},
    )
    with pytest.raises(AudiaGenticError):
        registry.document()


def test_migration_source_hash_recovers_crash_before_legacy_retirement(root, monkeypatch):
    from audiagentic.components.providers.services.mcp.managed_mcp_registry import (
        McpOwnershipRegistry,
    )
    from audiagentic.foundation.io import atomic_write_json

    registry = McpOwnershipRegistry(root)
    atomic_write_json(
        registry.legacy_path, {"contract-version": "v1", "providers": {"pi": {"one": "old"}}}
    )
    unlink = Path.unlink

    def crash(path, *args, **kwargs):
        if path == registry.legacy_path:
            raise OSError("before retiring v1")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", crash)
    with pytest.raises(OSError):
        registry.write_document(
            {
                "contract-version": "v2",
                "providers": {"pi/component-mcp": {"one": "new"}},
                "proofs": {},
            }
        )
    migrated = registry.document()
    assert migrated["providers"] == {"pi/component-mcp": {"one": "new"}}
    before = registry.path.read_bytes(), registry.path.stat().st_mtime_ns
    monkeypatch.setattr(Path, "unlink", unlink)
    registry.write_document(migrated)
    assert not registry.legacy_path.exists()
    assert before == (registry.path.read_bytes(), registry.path.stat().st_mtime_ns)


def test_subset_cannot_rebase_proof_for_an_untouched_external_edit(root):
    entries = tuple(providers.ManagedMcpEntry(mid, mid, command="python") for mid in ("one", "two"))
    request = providers.ManagedMcpRequest("subset-fixture", None, entries)
    plan = providers.preflight_managed_mcp(root, "pi", request=request)
    assert providers.apply_managed_mcp(
        root, "pi", request=request, expected_revision=plan["revision"]
    )["ok"]
    path = root / ".pi/mcp.json"
    data = json.loads(path.read_text())
    data["mcpServers"]["two"]["user_option"] = "preserve"
    path.write_text(json.dumps(data), encoding="utf8")
    registry = root / ".audiagentic/state/providers/managed-mcp-servers.json"
    before = path.read_bytes(), registry.read_bytes()
    subset = providers.ManagedMcpRequest(
        "subset-fixture",
        frozenset({"one"}),
        (providers.ManagedMcpEntry("one", "one", command="different"),),
    )
    with pytest.raises(AudiaGenticError):
        providers.preflight_managed_mcp(root, "pi", request=subset)
    assert before == (path.read_bytes(), registry.read_bytes())


def test_dry_run_creates_no_project_files(root):
    outcome = project.install_mcp(root, mcp_id="ag-planning", harness_ids=["pi"], dry_run=True)
    assert outcome["ok"] and not outcome["changed"]
    assert "operation_id" not in outcome
    assert not list(root.iterdir())


def test_detailed_help_never_registers_implementation_metadata(root, monkeypatch):
    from audiagentic.foundation.features import loader

    monkeypatch.setattr(
        loader,
        "register",
        lambda *a, **k: pytest.fail("metadata-only help registered runtime state"),
    )
    assert project.get_mcp_help("ag-planning", root)["mcp_id"] == "ag-planning"
    assert not list(root.iterdir())


def test_target_discovery_reads_prepared_identities_without_claiming_ownership(root, monkeypatch):
    from types import SimpleNamespace

    from audiagentic.components.providers.services.mcp import managed_mcp_registry

    registry = SimpleNamespace(
        document=lambda: {
            "providers": {"opencode/component-mcp": {}},
            "prepared": {"pi/component-mcp": {}},
        },
        load=lambda: pytest.fail("prepared transitions do not grant ordinary ownership"),
    )
    monkeypatch.setattr(managed_mcp_registry, "mcp_ownership_registry", lambda _: registry)
    assert providers.list_component_mcp_targets(root) == ("opencode", "pi")


def test_multiple_mcps_selection_removal_refresh_and_noop(root):
    assert project.install_mcp(root, mcp_id="ag-planning", harness_ids=["pi", "codex"])["ok"]
    assert project.install_mcp(root, mcp_id="ag-ledger", harness_ids=["pi"])["ok"]
    outcome = project.install_mcp(root, mcp_id="ag-planning", harness_ids=["codex"])
    assert outcome["ok"] and outcome["removed_harness_ids"] == ["pi"]
    assert set(json.loads((root / ".pi/mcp.json").read_text())["mcpServers"]) == {"ag-ledger"}
    paths = [
        root / ".pi/mcp.json",
        root / ".codex/config.toml",
        root / ".audiagentic/state/providers/managed-mcp-servers.json",
    ]
    before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
    assert project.reconcile_mcp_bindings(root) == []
    assert not project.install_mcp(root, mcp_id="ag-planning", harness_ids=["codex"])["changed"]
    assert before == [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
    assert project.get_mcp_install_status(root) == {"has_unresolved_operation": False}


def test_foreign_equal_payload_never_adopted(root):
    project.install_mcp(root, mcp_id="ag-planning", harness_ids=["pi"])
    registry = root / ".audiagentic/state/providers/managed-mcp-servers.json"
    registry.unlink()
    before = (root / ".pi/mcp.json").read_bytes()
    with pytest.raises(AudiaGenticError):
        project.install_mcp(root, mcp_id="ag-planning", harness_ids=["pi"], dry_run=True)
    assert (root / ".pi/mcp.json").read_bytes() == before
    assert not registry.exists()


def test_full_raw_entry_fingerprint_catches_unknown_user_fields(root):
    project.install_mcp(root, mcp_id="ag-planning", harness_ids=["codex"])
    native = root / ".codex/config.toml"
    native.write_text(native.read_text() + "\nstartup_timeout_sec = 999\n")
    before = native.read_bytes()
    with pytest.raises(AudiaGenticError):
        project.install_mcp(root, mcp_id="ag-planning", harness_ids=["codex"], dry_run=True)
    assert native.read_bytes() == before


def test_all_targets_preflight_before_any_mutation(root):
    path = root / ".pi/mcp.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"mcpServers": {"ag-planning": {"command": "foreign"}}}))
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(AudiaGenticError):
        project.install_mcp(root, mcp_id="ag-planning", harness_ids=["codex", "pi"])
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_partial_operation_resumes_same_id_without_repeating_completed_writes(root, monkeypatch):
    actual = providers.apply_managed_mcp

    def fail_second(path, pid, **kwargs):
        if pid == "pi":
            raise OSError("injected writer failure")
        return actual(path, pid, **kwargs)

    monkeypatch.setattr(providers, "apply_managed_mcp", fail_second)
    first = project.install_mcp(root, mcp_id="ag-planning", harness_ids=["opencode", "pi"])
    assert not first["ok"] and first["phase"] == "needs_reconciliation"
    native = root / ".opencode/opencode.json"
    before = native.read_bytes(), native.stat().st_mtime_ns
    monkeypatch.setattr(providers, "apply_managed_mcp", actual)
    second = project.install_mcp(root, mcp_id="ag-planning", harness_ids=["opencode", "pi"])
    assert second["ok"] and second["operation_id"] == first["operation_id"]
    assert before == (native.read_bytes(), native.stat().st_mtime_ns)
    assert len(second["applied_changes"]) == 2


def test_provider_cas_rejects_changed_file(root):
    entry = providers.ManagedMcpEntry("test", "test", command=sys.executable)
    request = providers.ManagedMcpRequest("test", None, (entry,))
    plan = providers.preflight_managed_mcp(root, "pi", request=request)
    native = root / ".pi/mcp.json"
    native.parent.mkdir()
    native.write_text('{"user": true}')
    with pytest.raises(AudiaGenticError):
        providers.apply_managed_mcp(root, "pi", request=request, expected_revision=plan["revision"])
    assert native.read_text() == '{"user": true}'


@pytest.mark.parametrize(
    "mcp_id,targets",
    [
        ("ag-planning-mgmt", ["pi"]),
        ("unknown", ["pi"]),
        ("ag-planning", []),
        ("ag-planning", ["unknown"]),
    ],
)
def test_invalid_input_is_nonmutating(root, mcp_id, targets):
    with pytest.raises(AudiaGenticError):
        project.install_mcp(root, mcp_id=mcp_id, harness_ids=targets)
    assert not list(root.iterdir())


def test_metadata_and_selective_protocol_output(root):
    from audiagentic.components.project.project_mcp import build_server
    from audiagentic.foundation.components.registry import get_mcp_server_declaration

    async def exercise():
        server = build_server()
        tools = {t.name: t for t in await server.list_tools()}
        declaration = get_mcp_server_declaration("project", "ag-project-mgmt")
        assert set(tools) == set(declaration.direct_tools) == set(declaration.tool_descriptions)
        assert len(tools) == 22  # 19 actual baseline tools plus three additions.
        assert tools["install_mcp"].inputSchema["properties"]["harness_ids"]["description"]
        result = await server.call_tool("get_mcp_install_status", {})
        assert result.content == []
        assert result.structuredContent == {"result": {"has_unresolved_operation": False}}
        validate(result.structuredContent, tools["get_mcp_install_status"].outputSchema)
        old = await server.call_tool("get_option_provenance", {})
        assert isinstance(old, tuple) and old[0]  # Existing text channel retained.

    asyncio.run(exercise())


def test_cli_discovery_does_not_initialize_runtime_or_adapters(root):
    source = Path(__file__).resolve().parents[3] / "src"
    env = {**os.environ, "PYTHONPATH": str(source), "AUDIAGENTIC_REPO_ROOT": str(root)}
    script = """
import sys
from audiagentic.launcher import _main
assert _main(['mcp','list','output','json']) == 0
assert 'audiagentic.runtime.harness' not in sys.modules
assert not any(n.startswith('audiagentic.components.providers.adapters') for n in sys.modules)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    assert len(completed.stdout.encode()) < 8192
    assert not list(root.iterdir())


@pytest.mark.parametrize(
    "command",
    [
        ["help"],
        ["mcp", "help"],
        ["mcp", "-h"],
        ["mcp", "install", "help"],
        ["mcp", "ag-planning", "help"],
        ["harness", "list"],
        ["harness", "pi", "help"],
    ],
)
def test_cli_help_paths_are_nonmutating(root, capsys, command):
    from audiagentic.launcher import _main

    assert _main(command) == 0
    assert capsys.readouterr().out
    assert not list(root.iterdir())


def test_cli_root_escape_and_literal_module_use_same_parser(root, monkeypatch):
    from types import SimpleNamespace

    from audiagentic import launcher
    from audiagentic.runtime import bootstrap

    graph = SimpleNamespace(
        shutdown=lambda: None, root=lambda _key: SimpleNamespace(start=lambda **_kw: None)
    )
    monkeypatch.setattr(bootstrap, "build_application_graph", lambda **_kw: graph)
    launched = []
    monkeypatch.setattr(
        launcher, "_cmd_launch", lambda root, tokens, params: launched.append(tokens) or 0
    )
    assert launcher._main(["--project", str(root), "--", "mcp", "--opaque"]) == 0
    assert launched == [["mcp", "--opaque"]]
    modules = []
    monkeypatch.setitem(
        launcher._COMMAND_HANDLERS,
        "mcp",
        lambda args, root: modules.append((args.module, args.module_args)) or 0,
    )
    assert launcher._main(["mcp", "--", "install", "help", "--opaque"]) == 0
    assert modules == [("install", ["help", "--opaque"])]


@pytest.mark.parametrize(
    "tail",
    [
        ["install"],
        ["install", "ag-planning", "harness", ""],
        ["install", "ag-planning", "harness", "pi,"],
        ["install", "ag-planning", "harness", "pi", "dry-run", "dry-run"],
        ["list", "unknown-clause"],
    ],
)
def test_malformed_management_never_starts_application(root, monkeypatch, tail):
    from audiagentic.launcher import _main
    from audiagentic.runtime import bootstrap

    monkeypatch.setattr(
        bootstrap,
        "build_application_graph",
        lambda **_kw: pytest.fail("malformed management launched the application"),
    )
    with pytest.raises(SystemExit) as exc:
        _main(["mcp", *tail])
    assert exc.value.code == 2
    assert not list(root.iterdir())


def test_component_disable_enable_uses_persisted_selection(root):
    project.install_mcp(root, mcp_id="ag-planning", harness_ids=["pi"])
    project.disable_component(root, "agent-planning")
    assert not json.loads((root / ".pi/mcp.json").read_text())["mcpServers"]
    project.enable_component(root, "agent-planning")
    assert set(json.loads((root / ".pi/mcp.json").read_text())["mcpServers"]) == {"ag-planning"}
    assert not (root / ".codex/config.toml").exists()


def test_damaged_history_does_not_block_new_installation(root):
    path = root / ".audiagentic/state/mcp-onboarding/operations/broken.json"
    path.parent.mkdir(parents=True)
    path.write_text("{damaged", encoding="utf8")
    assert project.install_mcp(root, mcp_id="ag-planning", harness_ids=["pi"])["ok"]
    assert project.get_mcp_install_status(root)["phase"] == "needs_reconciliation"
    assert path.read_text() == "{damaged"


def test_owner_requirements_use_schema_and_hide_sensitive_defaults(root, monkeypatch):
    from types import SimpleNamespace

    from audiagentic.components.project.onboarding import requirements
    from audiagentic.foundation.features.base import OptionSchema

    implementation = SimpleNamespace(
        parent="owner",
        implementation_id="default",
        options_schema={
            "directory": OptionSchema("string", required=True),
            "api_key": OptionSchema("string", default="do-not-disclose"),
        },
    )
    monkeypatch.setattr(requirements, "read_implementation_metadata", lambda _: [implementation])
    monkeypatch.setattr(requirements, "resolve_active_implementation", lambda *a, **k: "default")
    monkeypatch.setattr(requirements, "get_component_state", lambda *a, **k: {})
    owner = SimpleNamespace(component_id="owner")
    assert "default" not in requirements.describe(root, "owner")[0]["fields"]["api_key"]
    with pytest.raises(AudiaGenticError):
        requirements.resolve(root, owner, None)
    config = root / "owner.yaml"
    config.write_text("options:\n  directory: sandbox\n", encoding="utf8")
    assert requirements.resolve(root, owner, config)["values"]["directory"] == "sandbox"
    config.write_text("options:\n  api_key: secret\n", encoding="utf8")
    with pytest.raises(AudiaGenticError):
        requirements.resolve(root, owner, config)


def test_resume_rejects_changed_profile_fingerprint(root):
    from audiagentic.components.project.onboarding import service

    result = project.install_mcp(root, mcp_id="ag-planning", harness_ids=["pi"])
    path = root / ".audiagentic/state/mcp-onboarding/operations" / f"{result['operation_id']}.json"
    record = json.loads(path.read_text())
    record.update(phase="applying", fingerprint="old-profile-fingerprint")
    path.write_text(json.dumps(record), encoding="utf8")
    before = (root / ".pi/mcp.json").read_bytes()
    resumed = service.resume(root)[0]
    assert not resumed["ok"] and resumed["phase"] == "needs_reconciliation"
    assert (root / ".pi/mcp.json").read_bytes() == before


def test_background_reconcile_resolves_selection_after_acquiring_fence(root, monkeypatch):
    from contextlib import contextmanager

    from audiagentic.components.project.onboarding import service
    from audiagentic.foundation.io import load_yaml_file, save_yaml_file

    assert project.install_mcp(root, mcp_id="ag-planning", harness_ids=["pi"])["ok"]

    @contextmanager
    def competing_install_finished(path):
        config_path = root / ".audiagentic/config/project.yaml"
        config = load_yaml_file(config_path)
        config["mcp-onboarding"]["bindings"]["ag-planning"] = []
        save_yaml_file(config_path, config, atomic=True)
        yield

    monkeypatch.setattr(service, "AdvisoryLock", competing_install_finished)
    assert project.reconcile_mcp_bindings(root) == []
    assert not json.loads((root / ".pi/mcp.json").read_text())["mcpServers"]


def test_onboarding_contribution_preserves_user_surface_and_is_idempotent(root):
    from audiagentic.components.providers.surfaces.manager import apply_provider_surfaces

    path = root / "AGENTS.md"
    path.write_text("User instructions remain here.\n", encoding="utf8")
    apply_provider_surfaces(root, provider_id="codex")
    text = path.read_text(encoding="utf8")
    assert "User instructions remain here." in text
    assert "MCP onboarding" in text and "complete native target selection" in text
    apply_provider_surfaces(root, provider_id="codex")
    assert path.read_text(encoding="utf8") == text


def test_profile_launch_change_requires_explicit_install(root, monkeypatch):
    assert project.install_mcp(root, mcp_id="ag-planning", harness_ids=["pi"])["ok"]
    native = root / ".pi/mcp.json"
    before = native.read_bytes()
    monkeypatch.setenv("AUDIAGENTIC_COMPONENT_PROFILE", "alternate")
    assert project.reconcile_mcp_bindings(root)
    assert native.read_bytes() == before
    dry = project.install_mcp(root, mcp_id="ag-planning", harness_ids=["pi"], dry_run=True)
    assert dry["planned_changes"] and not dry["changed"]
    assert project.install_mcp(root, mcp_id="ag-planning", harness_ids=["pi"])["ok"]
    entry = json.loads(native.read_text())["mcpServers"]["ag-planning"]
    assert entry["env"]["AUDIAGENTIC_COMPONENT_PROFILE"] == "alternate"


def test_provider_disable_prunes_and_enable_restores_persisted_selection(root):
    from audiagentic.components.providers.services.config.provider_config import (
        set_provider_enabled,
    )
    from audiagentic.foundation.io import load_yaml_file

    assert project.install_mcp(root, mcp_id="ag-planning", harness_ids=["pi"])["ok"]
    assert project.install_mcp(root, mcp_id="ag-ledger", harness_ids=["pi"])["ok"]
    assert providers.manage_mcp_entries(
        root,
        "pi",
        mode="apply",
        request=providers.ManagedMcpRequest(
            "independent-lsp",
            frozenset({"lsp"}),
            (providers.ManagedMcpEntry("lsp", "separate-lsp", command="python"),),
        ),
    ).ok
    native = root / ".pi/mcp.json"
    data = json.loads(native.read_text())
    data["mcpServers"]["foreign"] = {"command": "user-owned"}
    native.write_text(json.dumps(data), encoding="utf8")
    config = root / ".audiagentic/config/project.yaml"
    bindings = load_yaml_file(config)["mcp-onboarding"]["bindings"]
    set_provider_enabled(root, "pi", enabled=False)
    assert set(json.loads(native.read_text())["mcpServers"]) == {"foreign", "separate-lsp"}
    assert project.resume_mcp_installations(root) == []
    assert load_yaml_file(config)["mcp-onboarding"]["bindings"] == bindings
    assert not providers.is_native_mcp_target_enabled(root, "pi")
    set_provider_enabled(root, "pi", enabled=True)
    assert set(json.loads(native.read_text())["mcpServers"]) == {
        "foreign",
        "separate-lsp",
        "ag-planning",
        "ag-ledger",
    }
    assert project.reconcile_mcp_bindings(root) == []


def test_install_rechecks_provider_state_after_lifecycle(root, monkeypatch):
    from audiagentic.components.providers.services.config.provider_config import (
        set_provider_enabled,
    )
    from audiagentic.foundation.lifecycle import components

    actual_install = components.install_component

    def disable_during_install(component_id, project_root):
        result = actual_install(component_id, project_root)
        if component_id == "agent-planning":
            set_provider_enabled(project_root, "pi", enabled=False)
        return result

    monkeypatch.setattr(components, "install_component", disable_during_install)
    result = project.install_mcp(root, mcp_id="ag-planning", harness_ids=["pi"])
    assert result["ok"] and not result["targets"][0]["configured"]
    native = root / ".pi/mcp.json"
    assert not native.exists() or not json.loads(native.read_text())["mcpServers"]


def test_intent_write_failure_has_terminal_actionable_record(root, monkeypatch):
    from audiagentic.components.project.onboarding import service

    def fail(*args, **kwargs):
        raise OSError("injected intent failure")

    monkeypatch.setattr(service, "save_yaml_file", fail)
    result = project.install_mcp(root, mcp_id="ag-planning", harness_ids=["pi"])
    assert not result["ok"] and result["phase"] == "needs_reconciliation"
    assert result["action_needed"]
    assert not (root / ".pi/mcp.json").exists()


def test_owner_configuration_changed_after_preflight_is_rejected(root, monkeypatch):
    from audiagentic.components.project.onboarding import requirements

    monkeypatch.setattr(
        requirements, "get_component_state", lambda *a, **k: {"options": {"changed": True}}
    )
    with pytest.raises(AudiaGenticError):
        requirements.validate_current(root, "agent-planning", {"state": {}})


def test_repeating_owner_options_never_rewrites_state(root, monkeypatch):
    from audiagentic.components.project.onboarding import requirements

    state = {"options": {"directory": "same"}}
    monkeypatch.setattr(requirements, "get_component_state", lambda *a, **k: state)
    monkeypatch.setattr(
        requirements,
        "set_component_state",
        lambda *a, **k: pytest.fail("no-op rewrote owner state"),
    )
    assert not requirements.persist(
        root, "owner", {"state": state, "options": {"directory": "same"}}
    )


@pytest.mark.parametrize("ids", ["pi", [None], [{}], [], [""]])
def test_owner_api_rejects_malformed_target_selection(root, ids):
    with pytest.raises(AudiaGenticError):
        project.install_mcp(root, mcp_id="ag-planning", harness_ids=ids)
    assert not list(root.iterdir())


@pytest.mark.parametrize("ids", ["a", [1], ["a", "a"], {}])
def test_managed_request_rejects_invalid_subsets(ids):
    with pytest.raises(ValueError):
        providers.ManagedMcpRequest.from_mapping(
            {"ownership_scope": "component-mcp", "managed_ids": ids}
        )


def test_managed_request_empty_subset_and_complete_scope_are_distinct():
    assert (
        providers.ManagedMcpRequest.from_mapping(
            {"ownership_scope": "x", "managed_ids": []}
        ).managed_ids
        == frozenset()
    )
    assert (
        providers.ManagedMcpRequest.from_mapping(
            {"ownership_scope": "x", "managed_ids": None}
        ).managed_ids
        is None
    )
