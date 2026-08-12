"""ON02: reconcile_provider honors reconciliation-policy before auto-enabling.

Follows test_provisioning.py's convention of monkeypatching
lifecycle.probe_provider_cli to simulate CLI presence without touching the
real host.
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.services.config.provider_config import (
    is_provider_enabled,
    set_reconciliation_policy,
)
from audiagentic.components.providers.services.lifecycle.lifecycle import (
    reconcile_all_providers,
    reconcile_provider,
)

_AVAILABLE_PROBE = {
    "available": True,
    "command": ["codex", "--version"],
    "executable": "/usr/bin/codex",
    "returncode": 0,
    "stdout": "1.0",
    "stderr": "",
}


def test_allowlist_mode_skips_detected_provider_not_in_allowlist(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.lifecycle.lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "probe_provider_cli", lambda d: _AVAILABLE_PROBE)
    set_reconciliation_policy(tmp_path, mode="allowlist", allowed_providers=["claude"])

    result = reconcile_provider("codex", project_root=tmp_path)

    assert result["status"] == "skipped"
    assert result["cli-available"] is True
    assert result["enabled"] is False
    assert is_provider_enabled(tmp_path, "codex") is False


def test_allowlist_mode_still_enables_an_allowed_provider(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.lifecycle.lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "probe_provider_cli", lambda d: _AVAILABLE_PROBE)
    set_reconciliation_policy(tmp_path, mode="allowlist", allowed_providers=["codex"])

    result = reconcile_provider("codex", project_root=tmp_path)

    assert result["status"] == "enabled"
    assert result["enabled"] is True
    assert is_provider_enabled(tmp_path, "codex") is True


def test_auto_mode_is_unchanged_regression(monkeypatch, tmp_path: Path) -> None:
    """Default policy (never configured) must behave exactly as before ON02."""
    import audiagentic.components.providers.services.lifecycle.lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "probe_provider_cli", lambda d: _AVAILABLE_PROBE)

    result = reconcile_provider("codex", project_root=tmp_path)

    assert result["status"] == "enabled"
    assert is_provider_enabled(tmp_path, "codex") is True


def test_explicit_auto_mode_also_enables_everything_detected(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.lifecycle.lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "probe_provider_cli", lambda d: _AVAILABLE_PROBE)
    set_reconciliation_policy(tmp_path, mode="auto")

    result = reconcile_provider("codex", project_root=tmp_path)

    assert result["status"] == "enabled"


def test_prompt_mode_with_no_decisions_yet_skips_like_allowlist(
    monkeypatch, tmp_path: Path
) -> None:
    """prompt mode, before anything has been decided, must not silently
    auto-enable — it behaves like an empty allowlist until ON03's interactive
    flow (or a direct set_reconciliation_policy call) decides a provider."""
    import audiagentic.components.providers.services.lifecycle.lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "probe_provider_cli", lambda d: _AVAILABLE_PROBE)
    set_reconciliation_policy(tmp_path, mode="prompt")

    result = reconcile_provider("codex", project_root=tmp_path)

    assert result["status"] == "skipped"
    assert is_provider_enabled(tmp_path, "codex") is False


def test_reconcile_all_providers_only_enables_allowed_providers(
    monkeypatch, tmp_path: Path
) -> None:
    import audiagentic.components.providers.services.lifecycle.lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "probe_provider_cli", lambda d: _AVAILABLE_PROBE)
    set_reconciliation_policy(tmp_path, mode="allowlist", allowed_providers=["claude", "codex"])

    result = reconcile_all_providers(project_root=tmp_path)

    statuses = {entry["provider-id"]: entry["status"] for entry in result["providers"]}
    assert statuses["claude"] == "enabled"
    assert statuses["codex"] == "enabled"
    # Every other CLI-eligible provider was detected as "available" by the
    # monkeypatch but is outside the allowlist, so it must be skipped, not enabled.
    other_statuses = {pid: status for pid, status in statuses.items() if pid not in ("claude", "codex")}
    assert other_statuses, "expected other providers in the registry to exercise the skip path"
    assert all(status == "skipped" for status in other_statuses.values())


def test_component_install_defers_reconciliation_until_initial_choice(monkeypatch, tmp_path: Path) -> None:
    """The post-install hook must not auto-enable CLIs before first-run selection."""
    import audiagentic.components.providers.services.reconcile as reconcile
    import audiagentic.foundation.components.registry as registry

    calls: list[Path] = []
    monkeypatch.setattr(registry, "is_installed", lambda _component, _root: True)
    monkeypatch.setattr(reconcile, "reconcile_all_providers", lambda **kwargs: calls.append(kwargs["project_root"]))

    reconcile.reconcile_all(tmp_path)

    assert calls == []
