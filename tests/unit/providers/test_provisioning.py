from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.descriptors.registry import all_descriptors
from audiagentic.components.providers.services.lifecycle import (
    provision_all_provider_clis,
    reconcile_all_providers,
    reconcile_provider,
)
from audiagentic.foundation.features.registry import get_implementation


def test_registry_includes_local_llm_harness_providers() -> None:
    providers = all_descriptors()

    assert {"aider", "goose", "openhands", "roo"}.issubset(providers)


def test_provider_descriptors_register_feature_implementations() -> None:
    providers = all_descriptors()

    assert get_implementation("providers", "codex") is not None
    assert get_implementation("providers", "claude") is not None
    assert get_implementation("providers", "codex").display_name == providers["codex"].display_name


def test_all_provider_cli_dry_run_covers_installable_providers() -> None:
    result = provision_all_provider_clis("install", dry_run=True)
    providers = {entry["provider-id"]: entry for entry in result["providers"]}

    assert result["ok"] is True
    assert providers["aider"]["package-manager"] == "uv"
    assert providers["codex"]["package-name"] == "@openai/codex"
    assert providers["claude"]["package-name"] == "@anthropic-ai/claude-code"
    assert providers["cline"]["package-name"] == "cline"
    assert providers["continue"]["package-name"] == "@continuedev/cli"
    assert providers["copilot"]["package-name"] == "@github/copilot"
    assert providers["copilot"]["package-manager"] == "npm"
    assert providers["gemini"]["package-name"] == "@google/gemini-cli"
    assert providers["goose"]["package-manager"] == "script"
    assert providers["openhands"]["package-manager"] == "uv"
    assert providers["opencode"]["package-name"] == "opencode-ai"
    assert providers["pi"]["package-manager"] == "pi-harness"
    assert providers["qwen"]["package-name"] == "@qwen-code/qwen-code"
    assert providers["local-openai"]["status"] == "skipped"
    assert providers["roo"]["package-manager"] == "vscode"


# --- reconcile tests ---

def test_reconcile_provider_enables_when_cli_available_and_not_enabled(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.lifecycle as lifecycle

    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": True, "command": ["codex", "--version"],
                   "executable": "/usr/bin/codex", "returncode": 0, "stdout": "1.0", "stderr": ""},
    )

    result = reconcile_provider("codex", project_root=tmp_path)

    assert result["status"] == "enabled"
    assert result["cli-available"] is True
    assert result["was-enabled"] is False
    assert result["action"] == "reconcile"


def test_reconcile_provider_disables_when_cli_absent_and_was_enabled(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.lifecycle as lifecycle
    from audiagentic.components.providers.services.provider_config import (
        set_provider_enabled,
    )

    set_provider_enabled(tmp_path, "codex", enabled=True)
    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": False, "command": ["codex", "--version"],
                   "executable": None, "returncode": None, "stdout": "", "stderr": "not found"},
    )

    result = reconcile_provider("codex", project_root=tmp_path)

    assert result["status"] == "disabled"
    assert result["cli-available"] is False
    assert result["was-enabled"] is True


def test_reconcile_provider_noop_when_already_in_sync_enabled(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.lifecycle as lifecycle
    from audiagentic.components.providers.services.provider_config import (
        set_provider_enabled,
    )

    set_provider_enabled(tmp_path, "codex", enabled=True)
    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": True, "command": ["codex", "--version"],
                   "executable": "/usr/bin/codex", "returncode": 0, "stdout": "1.0", "stderr": ""},
    )

    result = reconcile_provider("codex", project_root=tmp_path)

    assert result["status"] == "ok"
    assert "surfaces" not in result


def test_reconcile_provider_noop_when_already_in_sync_disabled(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.lifecycle as lifecycle

    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": False, "command": ["codex", "--version"],
                   "executable": None, "returncode": None, "stdout": "", "stderr": "not found"},
    )

    result = reconcile_provider("codex", project_root=tmp_path)

    assert result["status"] == "ok"
    assert "surfaces" not in result


def test_reconcile_all_providers_returns_one_entry_per_descriptor(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.lifecycle as lifecycle

    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": False, "command": [], "executable": None,
                   "returncode": None, "stdout": "", "stderr": ""},
    )

    result = reconcile_all_providers(project_root=tmp_path)

    assert result["action"] == "reconcile"
    assert result["ok"] is True
    expected = {
        pid for pid, d in all_descriptors().items()
        if not (d.cli_install and d.cli_install.package_manager == "vscode")
    }
    provider_ids = {entry["provider-id"] for entry in result["providers"]}
    assert provider_ids == expected


def test_reconcile_provider_does_not_fetch_catalog_by_default(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.catalog as catalog_mod
    import audiagentic.components.providers.services.lifecycle as lifecycle

    catalog_called: list[str] = []

    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": True, "command": ["claude", "--version"],
                   "executable": "/usr/bin/claude", "returncode": 0, "stdout": "1.0", "stderr": ""},
    )
    monkeypatch.setattr(
        catalog_mod,
        "fetch_provider_catalog",
        lambda provider_id, **_: catalog_called.append(provider_id) or {"ok": True},
    )

    reconcile_provider("claude", project_root=tmp_path)

    assert catalog_called == [], "catalog fetch must not run when fetch_catalog=False"


def test_reconcile_provider_fetches_catalog_when_flag_set(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.lifecycle as lifecycle

    catalog_called: list[str] = []

    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": True, "command": ["claude", "--version"],
                   "executable": "/usr/bin/claude", "returncode": 0, "stdout": "1.0", "stderr": ""},
    )

    import audiagentic.components.providers.services.catalog as catalog_mod
    monkeypatch.setattr(
        catalog_mod,
        "fetch_provider_catalog",
        lambda provider_id, **_: catalog_called.append(provider_id) or {"ok": True, "model_count": 3},
    )

    result = reconcile_provider("claude", project_root=tmp_path, fetch_catalog=True)

    assert result["status"] == "enabled"
    assert "claude" in catalog_called


def test_reconcile_provider_emits_progress(monkeypatch, tmp_path: Path) -> None:
    import audiagentic.components.providers.services.lifecycle as lifecycle

    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": True, "command": ["codex", "--version"],
                   "executable": "/usr/bin/codex", "returncode": 0, "stdout": "1.0", "stderr": ""},
    )

    events: list[str] = []
    reconcile_provider("codex", project_root=tmp_path, on_progress=lambda e: events.append(e.message))

    assert any("codex" in msg.lower() or "probing" in msg.lower() for msg in events)
    assert len(events) >= 2


def test_reconcile_all_providers_does_not_fetch_catalogs_by_default(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.catalog as catalog_mod
    import audiagentic.components.providers.services.lifecycle as lifecycle

    catalog_called: list[str] = []

    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": False, "command": [], "executable": None,
                   "returncode": None, "stdout": "", "stderr": ""},
    )
    monkeypatch.setattr(
        catalog_mod,
        "fetch_provider_catalog",
        lambda provider_id, **_: catalog_called.append(provider_id) or {"ok": True},
    )

    reconcile_all_providers(project_root=tmp_path)

    assert catalog_called == [], "no catalog fetches should occur by default"


def test_reconcile_all_providers_emits_progress_with_total(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.lifecycle as lifecycle
    from audiagentic.foundation.contracts.output import ComponentOutputEvent

    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": False, "command": [], "executable": None,
                   "returncode": None, "stdout": "", "stderr": ""},
    )

    progress_events: list[ComponentOutputEvent] = []
    reconcile_all_providers(project_root=tmp_path, on_progress=progress_events.append)

    timed = [e for e in progress_events if e.progress is not None and e.total is not None]
    assert timed, "expected at least one progress event with total"
    assert all(e.total > 0 for e in timed)
    assert all(e.progress <= e.total for e in timed)


# --- CLI lifecycle registry tests ---

def test_cli_lifecycle_plan_returns_installed_when_cli_available(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.lifecycle as lifecycle

    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": True, "command": ["codex", "--version"],
                   "executable": "/usr/bin/codex", "returncode": 0, "stdout": "1.0", "stderr": ""},
    )

    from audiagentic.components.providers.services.automation_registry import (
        build_automation_registry,
    )

    registry = build_automation_registry(tmp_path)
    result = registry.dispatch("codex", "cli-lifecycle", "plan", {})

    assert result.ok is True
    assert result.supported is True
    assert result.state == "installed"
    assert result.changed is False


def test_cli_lifecycle_plan_returns_skipped_when_cli_absent(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.lifecycle as lifecycle

    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": False, "command": ["codex", "--version"],
                   "executable": None, "returncode": None, "stdout": "", "stderr": "not found"},
    )

    from audiagentic.components.providers.services.automation_registry import (
        build_automation_registry,
    )

    registry = build_automation_registry(tmp_path)
    result = registry.dispatch("codex", "cli-lifecycle", "plan", {})

    assert result.ok is True
    assert result.supported is True
    assert result.state == "skipped"


def test_cli_lifecycle_status_returns_installed_when_cli_available(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.lifecycle as lifecycle

    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": True, "command": ["codex", "--version"],
                   "executable": "/usr/bin/codex", "returncode": 0, "stdout": "1.0", "stderr": ""},
    )

    from audiagentic.components.providers.services.automation_registry import (
        build_automation_registry,
    )

    registry = build_automation_registry(tmp_path)
    result = registry.dispatch("codex", "cli-lifecycle", "status", {})

    assert result.ok is True
    assert result.supported is True
    assert result.state == "installed"


def test_cli_lifecycle_status_returns_uninstalled_when_cli_absent(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.lifecycle as lifecycle

    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": False, "command": ["codex", "--version"],
                   "executable": None, "returncode": None, "stdout": "", "stderr": "not found"},
    )

    from audiagentic.components.providers.services.automation_registry import (
        build_automation_registry,
    )

    registry = build_automation_registry(tmp_path)
    result = registry.dispatch("codex", "cli-lifecycle", "status", {})

    assert result.ok is True
    assert result.supported is True
    assert result.state == "uninstalled"


def test_cli_lifecycle_apply_noop_when_already_installed(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.lifecycle as lifecycle

    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": True, "command": ["codex", "--version"],
                   "executable": "/usr/bin/codex", "returncode": 0, "stdout": "1.0", "stderr": ""},
    )

    from audiagentic.components.providers.services.automation_registry import (
        build_automation_registry,
    )

    registry = build_automation_registry(tmp_path)
    result = registry.dispatch("codex", "cli-lifecycle", "apply", {})

    assert result.ok is True
    assert result.supported is True
    assert result.state == "installed"
    assert result.changed is False


def test_cli_lifecycle_prune_noop_when_already_uninstalled(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.lifecycle as lifecycle

    monkeypatch.setattr(
        lifecycle,
        "_probe_provider_cli",
        lambda d: {"available": False, "command": ["codex", "--version"],
                   "executable": None, "returncode": None, "stdout": "", "stderr": "not found"},
    )

    from audiagentic.components.providers.services.automation_registry import (
        build_automation_registry,
    )

    registry = build_automation_registry(tmp_path)
    result = registry.dispatch("codex", "cli-lifecycle", "prune", {})

    assert result.ok is True
    assert result.supported is True
    assert result.state == "uninstalled"
    assert result.changed is False


def test_cli_lifecycle_result_has_no_raw_mechanic_fields() -> None:
    """CliLifecycleResult must not expose command, returncode, stdout, stderr,
    workflow-events, or probe dict — redaction per Architecture Standards §4."""
    from audiagentic.components.providers.contracts.cli_lifecycle import CliLifecycleResult

    result = CliLifecycleResult(ok=True, supported=True, state="installed")
    mapping = result.to_mapping()

    assert "command" not in mapping
    assert "returncode" not in mapping
    assert "stdout" not in mapping
    assert "stderr" not in mapping
    assert "workflow-events" not in mapping
    assert "probe" not in mapping
    assert "action" not in mapping


def test_cli_lifecycle_result_to_mapping_contains_semantic_fields() -> None:
    from audiagentic.components.providers.contracts.cli_lifecycle import CliLifecycleResult

    result = CliLifecycleResult(
        ok=True, supported=True, changed=True, state="installed",
        action_needed=None, error_code=None,
    )
    mapping = result.to_mapping()

    assert mapping["ok"] is True
    assert mapping["supported"] is True
    assert mapping["changed"] is True
    assert mapping["state"] == "installed"
    assert mapping["action_needed"] is None
    assert mapping["error_code"] is None


def test_automation_registry_registers_cli_for_providers_with_cli_install(
    tmp_path: Path,
) -> None:
    from audiagentic.components.providers.services.automation_registry import (
        build_automation_registry,
    )

    registry = build_automation_registry(tmp_path)

    for pid, desc in all_descriptors().items():
        if desc.cli_install is None:
            continue
        if desc.automation_capability("cli-lifecycle") is None:
            continue
        definition = registry.definition_for(pid, "cli-lifecycle")
        assert definition is not None, f"{pid} should have cli-lifecycle registration"
        assert definition.family_id == "cli-lifecycle"
        assert definition.ownership_scope_required is False


def test_automation_registry_no_cli_for_local_openai(
    tmp_path: Path,
) -> None:
    from audiagentic.components.providers.services.automation_registry import (
        build_automation_registry,
    )

    registry = build_automation_registry(tmp_path)
    definition = registry.definition_for("local-openai", "cli-lifecycle")
    assert definition is None, "local-openai has no cli_install, must not register cli-lifecycle"
