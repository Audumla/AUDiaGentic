"""Comprehensive Docker e2e coverage for the MA managed-config capability matrix.

test_provider_full_lifecycle.py and test_provider_surface_lifecycle.py already
cover mcp_config and skill/instruction surfaces end to end, but only on the
happy path, for whichever providers each test hand-enumerates. This module
fills two real gaps found while auditing MA (managed-config-consistency)
closure:

1. plugin_config (opencode), hooks_config (codex), and model_config (pi) had
   ZERO Docker/mutation coverage anywhere in the suite — hooks_config and
   model_config resolve HOME-relative absolute paths
   (~/.codex/hooks.json, ~/.pi/agent/models.json) that no prior test ever
   actually exercised outside of pure-unit fixtures.
2. There was no negative/adversarial coverage anywhere: no test for a
   corrupted pre-existing config file, foreign-content preservation across
   repeated cycles, purge idempotency, purge completeness across every
   capability kind at once, duplicate-entry handling, or HOME-path isolation.

The mcp_config classes below are TEMPLATE suites, not per-provider
hand-written tests: they parametrize over every provider the shared
``tests.integration.providers.harness`` module considers installable that
declares an ``mcp_config`` (discovered from the live descriptor registry, via
``_mcp_provider_ids``), and drive corruption behavior off a small
format-keyed fixture table in ``mcp_format_fixtures.py`` — one row per wire
format (mcp-json, codex-toml, goose-yaml, continue-json, opencode-mcp,
mcp-toml), reused across every provider sharing that format. Foreign-content
and purge-idempotency tests need no format-specific fixtures at all, since
they only exercise the service layer's add/remove/list functions. A new
provider reusing an existing format, or a new format with one new fixture
row, is covered automatically without touching this file's test bodies.

RV713 (foundation/io.py:load_json_file, foundation/mcp/json_format.py,
codex/hooks_format.py, codex/language_servers.py, opencode/mcp_format.py,
continue_/mcp_format.py, openhands/toml_format.py all silently discarding
corrupted config content instead of raising) has been fixed. The corruption
tests below now assert the fix directly rather than xfail-documenting the
defect; ``mcp_format_fixtures.py``'s ``write_is_safe`` flag stays in place so
a future regression that reintroduces the swallow pattern for any format is
caught automatically instead of silently passing.

Run via: docker run --rm audiagentic-provider-config-matrix-e2e
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from tests.integration.providers import harness
from tests.integration.providers.mcp_format_fixtures import MCP_FORMAT_FIXTURES

from audiagentic.components.providers.adapters.pi.model_config import (
    read_pi_models,
    remove_pi_model,
    write_pi_models,
)
from audiagentic.components.providers.contracts.managed_hooks import (
    ManagedHooksEntry,
    ManagedHooksRequest,
)
from audiagentic.components.providers.contracts.plugin_entry import PluginEntryRequest
from audiagentic.components.providers.descriptors.registry import get_descriptor
from audiagentic.components.providers.services.capabilities.managed_hooks_family import (
    manage_hook_entries,
)
from audiagentic.components.providers.services.capabilities.plugin_entries import (
    manage_plugin_entry,
)
from audiagentic.components.providers.services.lifecycle.lifecycle import (
    install_provider_cli,
    uninstall_provider_cli,
)
from audiagentic.components.providers.services.mcp.mcp import (
    add_provider_mcp_server,
    list_provider_mcp_servers,
    remove_provider_mcp_server,
)
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.lifecycle.components import install_component
from audiagentic.foundation.toolchains.config.managed_config import resolve_managed_config_path

pytestmark = [
    pytest.mark.mutates_host,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("AUDIAGENTIC_DOCKER_TESTS") != "1",
        reason="managed-config capability matrix tests mutate real HOME-relative "
        "config paths and must run in Docker isolation",
    ),
]

register_all_components()

_REAL_CLI = pytest.mark.skipif(
    os.environ.get("AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS") != "1",
    reason="requires real provider CLI install",
)


def _mcp_provider_ids() -> list[str]:
    """Every provider the shared harness considers installable that also
    declares mcp_config — discovered live, never hand-enumerated."""
    return [
        pid
        for pid in harness.filtered_provider_ids()
        if (desc := get_descriptor(pid)) is not None and desc.mcp_config is not None
    ]


def _mcp_corruption_params() -> list[object]:
    """One pytest.param per mcp_config provider. Marked xfail(strict=True)
    only if a provider's format is still (or again) known to swallow
    corruption; skip if a provider uses a format with no registered fixture
    row yet. Every currently-registered format is write_is_safe=True post
    RV713-fix, so no param carries a mark today — the mechanism stays live
    for regression protection."""
    params = []
    for provider_id in _mcp_provider_ids():
        fmt = get_descriptor(provider_id).mcp_config.format
        fixture = MCP_FORMAT_FIXTURES.get(fmt)
        marks = []
        if fixture is None:
            marks.append(
                pytest.mark.skip(reason=f"no corruption fixture registered for mcp format {fmt!r}")
            )
        elif not fixture.write_is_safe:
            marks.append(
                pytest.mark.xfail(
                    strict=True,
                    reason=f"RV713: {provider_id} mcp_config writer ({fmt}) silently "
                    "discards corrupt config instead of raising",
                )
            )
        params.append(pytest.param(provider_id, id=provider_id, marks=marks))
    return params


def _project(tmp_path: Path) -> Path:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".audiagentic").mkdir(parents=True, exist_ok=True)
    install_component("providers", project_root)
    return project_root


def _isolated_home(tmp_path: Path, monkeypatch, name: str = "home") -> Path:
    """Redirect the home directory so ~-relative managed-config paths never
    touch the real one. Returns the redirected home directory.

    HOME alone is NOT enough: Windows Path.expanduser resolves USERPROFILE
    (then HOMEDRIVE/HOMEPATH) and ignores HOME entirely, so a HOME-only
    monkeypatch silently escapes isolation on a Windows host and mutates the
    operator's real ~/.claude, ~/.codex, ~/.gemini configs — which actually
    happened during this suite's development. Patch every resolution route."""
    home = tmp_path / name
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOMEDRIVE", str(home.drive) or "C:")
    monkeypatch.setenv("HOMEPATH", str(home)[len(home.drive) :] if home.drive else str(home))
    return home


@pytest.fixture(autouse=True)
def _sandbox_home_for_every_test(tmp_path: Path, monkeypatch) -> Path:
    """Every test in this module gets an isolated home, opted-in or not.

    install_component(\"providers\") fires the lifecycle observer, which syncs
    MCP config for ALL providers — including HOME-relative paths like
    ~/.claude/mcp.json and ~/.gemini/antigravity/mcp_config.json — so even a
    test that only targets a project-relative provider config transitively
    touches the home directory. Isolation therefore cannot be per-test
    opt-in. Explicit _isolated_home calls in test bodies are idempotent on
    top of this."""
    return _isolated_home(tmp_path, monkeypatch)


# --------------------------------------------------------------------------- #
# Full install -> apply -> prune -> uninstall lifecycle, per capability kind
# --------------------------------------------------------------------------- #


class TestPluginConfigLifecycle:
    """opencode plugin_config: the only provider declaring plugin-entry."""

    @_REAL_CLI
    @pytest.mark.timeout(600)
    def test_plugin_apply_status_prune_roundtrip(self, tmp_path: Path) -> None:
        project_root = _project(tmp_path)
        install_result = install_provider_cli("opencode", timeout=300, project_root=project_root)
        assert install_result.get("status") == "installed", install_result

        config_path = project_root / ".opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({"plugin": []}), encoding="utf-8")

        request = PluginEntryRequest(
            entry_id="@example/test-plugin",
            ownership_scope="ma34-test",
            options=(("verbose", "true"),),
        )
        applied = manage_plugin_entry(project_root, "opencode", mode="apply", request=request)
        assert applied.ok and applied.supported, applied

        status = manage_plugin_entry(project_root, "opencode", mode="status", request=request)
        assert status.present, "plugin entry not present after apply"

        raw = json.loads(config_path.read_text(encoding="utf-8"))
        names = {entry[0] if isinstance(entry, list) else entry for entry in raw["plugin"]}
        assert "@example/test-plugin" in names

        pruned = manage_plugin_entry(project_root, "opencode", mode="prune", request=request)
        assert pruned.ok

        status_after = manage_plugin_entry(project_root, "opencode", mode="status", request=request)
        assert not status_after.present, "plugin entry still present after prune"

        uninstall_provider_cli("opencode", timeout=300, project_root=project_root)


class TestHooksConfigLifecycle:
    """codex hooks_config: HOME-relative (~/.codex/hooks.json), restart-required."""

    @_REAL_CLI
    @pytest.mark.timeout(600)
    def test_hooks_apply_status_prune_roundtrip(self, tmp_path: Path, monkeypatch) -> None:
        home = _isolated_home(tmp_path, monkeypatch)
        project_root = _project(tmp_path)
        install_result = install_provider_cli("codex", timeout=300, project_root=project_root)
        assert install_result.get("status") == "installed", install_result

        request = ManagedHooksRequest(
            ownership_scope="ma34-test",
            entries=(
                ManagedHooksEntry(
                    managed_id="ma34-hook",
                    event="SessionStart",
                    command="echo ma34-hook-fired",
                    timeout=5,
                ),
            ),
        )
        applied = manage_hook_entries(project_root, "codex", mode="apply", request=request)
        assert applied.ok, applied
        assert "ma34-hook" in applied.managed_ids

        hooks_path = home / ".codex" / "hooks.json"
        assert hooks_path.exists(), "hooks.json not written under isolated HOME"
        data = json.loads(hooks_path.read_text(encoding="utf-8"))
        commands = {
            hook.get("command")
            for group in data.get("hooks", {}).get("SessionStart", [])
            for hook in group.get("hooks", [])
        }
        assert "echo ma34-hook-fired" in commands

        # write_codex_hooks bypasses config_path and hardcodes Path.home() for
        # the [features] hooks=true surgical upsert — verify it landed under
        # the ISOLATED home, not the real container home.
        config_toml = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
        assert "hooks = true" in config_toml

        pruned = manage_hook_entries(project_root, "codex", mode="prune", request=request)
        assert pruned.ok
        assert "ma34-hook" in pruned.removed_ids

        # remove_codex_hook unlinks hooks.json entirely once its hooks section
        # is empty (hooks_format.py:210-211) — assert that cleanup actually
        # happens, not just that our command is gone from a stale file.
        assert not hooks_path.exists(), "hooks.json not unlinked after last hook pruned"

        uninstall_provider_cli("codex", timeout=300, project_root=project_root)


class TestModelConfigCapability:
    """pi model_config: pi is excluded from Docker CLI install (special harness
    setup), so this exercises the reader/writer/remover trio directly against
    an isolated HOME — still real end-to-end config-file mutation, just without
    a live pi binary in front of it."""

    def test_model_write_read_remove_roundtrip_isolated_home(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        home = _isolated_home(tmp_path, monkeypatch)
        config_path = home / ".pi" / "agent" / "models.json"

        write_pi_models(
            config_path,
            {
                "ma34-model": (
                    "MA34 Test Model",
                    {
                        "model_id": "ma34-model",
                        "visible_name": "MA34 Test Model",
                        "provider": "test",
                    },
                )
            },
        )
        assert config_path.exists()
        assert config_path.is_relative_to(home), "models.json escaped isolated HOME"

        entries = read_pi_models(config_path)
        assert "ma34-model" in entries
        assert entries["ma34-model"][0] == "MA34 Test Model"

        removed = remove_pi_model(config_path, "ma34-model")
        assert removed
        assert "ma34-model" not in read_pi_models(config_path)

        # Second removal of the same id is a safe no-op, not an error.
        assert remove_pi_model(config_path, "ma34-model") is False


# --------------------------------------------------------------------------- #
# Template suite: mcp_config across every harness the shared test policy
# considers installable. Parametrized off the live descriptor registry, not
# hand-enumerated — a new provider or format is picked up automatically.
# --------------------------------------------------------------------------- #


class TestMcpConfigAcrossAllHarnesses:
    """Foreign-content preservation and purge idempotency need no
    format-specific fixtures: they only drive the service layer's
    add/remove/list functions, so one test body covers every mcp_config
    provider regardless of wire format."""

    @pytest.mark.parametrize("provider_id", _mcp_provider_ids())
    def test_foreign_entry_survives_managed_add_remove_cycles(
        self, provider_id: str, tmp_path: Path, monkeypatch
    ) -> None:
        harness.maybe_skip_provider(provider_id)
        _isolated_home(tmp_path, monkeypatch)
        project_root = _project(tmp_path)

        add_provider_mcp_server(
            provider_id, "ma34-foreign-fixture", "echo", project_root, args=("foreign",)
        )
        for _ in range(3):
            add_provider_mcp_server(
                provider_id, "ma34-managed", "echo", project_root, args=("managed",)
            )
            remove_provider_mcp_server(provider_id, "ma34-managed", project_root)

        names = {s["name"] for s in list_provider_mcp_servers(provider_id, project_root)["servers"]}
        assert "ma34-foreign-fixture" in names, (
            f"{provider_id}: foreign entry lost across managed add/remove cycles"
        )
        assert "ma34-managed" not in names

    @pytest.mark.parametrize("provider_id", _mcp_provider_ids())
    def test_purge_is_idempotent(self, provider_id: str, tmp_path: Path, monkeypatch) -> None:
        harness.maybe_skip_provider(provider_id)
        _isolated_home(tmp_path, monkeypatch)
        project_root = _project(tmp_path)

        add_provider_mcp_server(provider_id, "ma34-idempotent", "echo", project_root)

        first = remove_provider_mcp_server(provider_id, "ma34-idempotent", project_root)
        assert first["ok"] and first["removed"] is True

        second = remove_provider_mcp_server(provider_id, "ma34-idempotent", project_root)
        assert second["ok"], f"{provider_id}: second removal must not error"
        assert second["removed"] is False, f"{provider_id}: second removal must be a no-op"

    @pytest.mark.parametrize("provider_id", _mcp_provider_ids())
    def test_duplicate_add_upserts_not_duplicates(
        self, provider_id: str, tmp_path: Path, monkeypatch
    ) -> None:
        harness.maybe_skip_provider(provider_id)
        _isolated_home(tmp_path, monkeypatch)
        project_root = _project(tmp_path)

        add_provider_mcp_server(provider_id, "ma34-dup", "echo", project_root, args=("v1",))
        add_provider_mcp_server(provider_id, "ma34-dup", "echo", project_root, args=("v2",))

        matches = [
            s
            for s in list_provider_mcp_servers(provider_id, project_root)["servers"]
            if s["name"] == "ma34-dup"
        ]
        assert len(matches) == 1, (
            f"{provider_id}: expected one upserted entry, found {len(matches)}"
        )
        assert matches[0]["args"] == ["v2"], f"{provider_id}: second add did not upsert args"


class TestMcpConfigCorruptionAcrossAllHarnesses:
    """RV713 (fixed): mcp_config writers must raise on corrupted existing
    content rather than silently discard it. codex-toml and goose-yaml
    already raised correctly before the fix; every other format is fixed as
    of this suite."""

    @pytest.mark.parametrize("provider_id", _mcp_corruption_params())
    def test_corrupted_mcp_config_apply_must_not_silently_discard(
        self, provider_id: str, tmp_path: Path, monkeypatch
    ) -> None:
        harness.maybe_skip_provider(provider_id)
        _isolated_home(tmp_path, monkeypatch)
        project_root = _project(tmp_path)
        spec = get_descriptor(provider_id).mcp_config
        config_path = resolve_managed_config_path(spec, project_root)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        corrupt = MCP_FORMAT_FIXTURES[spec.format].corrupt
        config_path.write_text(corrupt, encoding="utf-8")

        with pytest.raises(Exception):
            add_provider_mcp_server(provider_id, "ma34-corrupt-probe", "echo", project_root)

        assert config_path.read_text(encoding="utf-8") == corrupt, (
            f"{provider_id} ({spec.format}): corrupted mcp config silently overwritten"
        )


# --------------------------------------------------------------------------- #
# Negative path: corrupted pre-existing config must never be silently discarded
# --------------------------------------------------------------------------- #


class TestCorruptedConfigMustNotBeSilentlyDiscarded:
    """RV713 (fixed): foundation/io.py:load_json_file and codex
    hooks_format.py's hand-rolled reader used to swallow JSONDecodeError and
    return {}, identical to the missing-file case, so the next managed write
    silently overwrote the corrupted file. Both now raise; these tests assert
    the fix directly."""

    def test_corrupted_hooks_json_apply_raises_and_leaves_file_untouched(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        home = _isolated_home(tmp_path, monkeypatch)
        project_root = _project(tmp_path)
        hooks_path = home / ".codex" / "hooks.json"
        hooks_path.parent.mkdir(parents=True, exist_ok=True)
        corrupted = '{"hooks": {"SessionStart": [ this is not valid json'
        hooks_path.write_text(corrupted, encoding="utf-8")

        request = ManagedHooksRequest(
            ownership_scope="ma34-corrupt-test",
            entries=(
                ManagedHooksEntry(
                    managed_id="ma34-hook",
                    event="SessionStart",
                    command="echo should-not-land",
                ),
            ),
        )
        with pytest.raises(Exception):
            manage_hook_entries(project_root, "codex", mode="apply", request=request)

        assert hooks_path.read_text(encoding="utf-8") == corrupted, (
            "corrupted hooks.json was silently overwritten instead of raising"
        )

    def test_corrupted_opencode_json_apply_raises_and_leaves_file_untouched(
        self, tmp_path: Path
    ) -> None:
        project_root = _project(tmp_path)
        config_path = project_root / ".opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        corrupted = '{"plugin": [ this is not valid json'
        config_path.write_text(corrupted, encoding="utf-8")

        request = PluginEntryRequest(entry_id="@example/x", ownership_scope="ma34-corrupt-test")
        with pytest.raises(Exception):
            manage_plugin_entry(project_root, "opencode", mode="apply", request=request)

        assert config_path.read_text(encoding="utf-8") == corrupted, (
            "corrupted opencode.json was silently overwritten instead of raising"
        )

    def test_corrupted_pi_models_json_write_raises_and_leaves_file_untouched(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Contrast case: pi/model_config.py does NOT catch JSONDecodeError at
        all, so it already fails loud and leaves the file untouched. This is
        the behavior every other adapter should converge on."""
        home = _isolated_home(tmp_path, monkeypatch)
        config_path = home / ".pi" / "agent" / "models.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        corrupted = '{"models": [ this is not valid json'
        config_path.write_text(corrupted, encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            write_pi_models(config_path, {"x": ("X", {"model_id": "x"})})

        assert config_path.read_text(encoding="utf-8") == corrupted


# --------------------------------------------------------------------------- #
# Foreign-content preservation across repeated apply/prune cycles
# --------------------------------------------------------------------------- #


class TestForeignContentPreserved:
    def test_foreign_plugin_entries_survive_repeated_managed_cycles(self, tmp_path: Path) -> None:
        project_root = _project(tmp_path)
        config_path = project_root / ".opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps({"plugin": ["@foreign/untouched", ["@foreign/with-opts", {"x": 1}]]}),
            encoding="utf-8",
        )

        request = PluginEntryRequest(entry_id="@ma34/managed", ownership_scope="ma34-foreign-test")
        for _ in range(3):
            manage_plugin_entry(project_root, "opencode", mode="apply", request=request)
            manage_plugin_entry(project_root, "opencode", mode="prune", request=request)

        raw = json.loads(config_path.read_text(encoding="utf-8"))
        names = {entry[0] if isinstance(entry, list) else entry for entry in raw["plugin"]}
        assert "@foreign/untouched" in names
        assert "@foreign/with-opts" in names
        assert "@ma34/managed" not in names

    def test_foreign_hook_survives_managed_apply_and_prune(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        home = _isolated_home(tmp_path, monkeypatch)
        project_root = _project(tmp_path)
        hooks_path = home / ".codex" / "hooks.json"
        hooks_path.parent.mkdir(parents=True, exist_ok=True)
        hooks_path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {"hooks": [{"type": "command", "command": "echo foreign-hook"}]}
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        request = ManagedHooksRequest(
            ownership_scope="ma34-foreign-hook-test",
            entries=(
                ManagedHooksEntry(
                    managed_id="ma34-hook", event="SessionStart", command="echo managed"
                ),
            ),
        )
        manage_hook_entries(project_root, "codex", mode="apply", request=request)
        manage_hook_entries(project_root, "codex", mode="prune", request=request)

        data = json.loads(hooks_path.read_text(encoding="utf-8"))
        commands = {
            hook.get("command")
            for group in data.get("hooks", {}).get("PreToolUse", [])
            for hook in group.get("hooks", [])
        }
        assert "echo foreign-hook" in commands, "foreign hook removed by managed prune"
        assert not any(
            hook.get("command") == "echo managed"
            for group in data.get("hooks", {}).get("SessionStart", [])
            for hook in group.get("hooks", [])
        )


# --------------------------------------------------------------------------- #
# Purge idempotency and cross-capability completeness
# --------------------------------------------------------------------------- #


class TestPurgeIdempotencyAndCompleteness:
    def test_prune_twice_is_a_clean_noop(self, tmp_path: Path) -> None:
        project_root = _project(tmp_path)
        config_path = project_root / ".opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({"plugin": []}), encoding="utf-8")

        request = PluginEntryRequest(
            entry_id="@ma34/idempotent", ownership_scope="ma34-idempotent-test"
        )
        manage_plugin_entry(project_root, "opencode", mode="apply", request=request)

        first_prune = manage_plugin_entry(project_root, "opencode", mode="prune", request=request)
        assert first_prune.ok

        second_prune = manage_plugin_entry(project_root, "opencode", mode="prune", request=request)
        assert second_prune.ok, "second prune must succeed cleanly, not error"
        assert not second_prune.changed, "second prune must be a no-op, not re-mutate"

    def test_mcp_purge_across_multiple_entries_leaves_zero_residue(self, tmp_path: Path) -> None:
        project_root = _project(tmp_path)
        desc = get_descriptor("codex")
        assert desc is not None and desc.mcp_config is not None
        config_path = project_root / ".codex" / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("", encoding="utf-8")

        for i in range(5):
            add_provider_mcp_server(
                "codex", f"ma34-server-{i}", "echo", project_root, args=(str(i),)
            )
        servers = list_provider_mcp_servers("codex", project_root)
        assert len(servers["servers"]) == 5

        for i in range(5):
            remove_provider_mcp_server("codex", f"ma34-server-{i}", project_root)
        servers_after = list_provider_mcp_servers("codex", project_root)
        assert servers_after["servers"] == []

        # Removing again — every entry already gone — must be a safe no-op.
        for i in range(5):
            result = remove_provider_mcp_server("codex", f"ma34-server-{i}", project_root)
            assert result["ok"]
            assert result["removed"] is False


# --------------------------------------------------------------------------- #
# Duplicate-entry and missing-entry handling
# --------------------------------------------------------------------------- #


class TestDuplicateAndMissingEntryHandling:
    def test_applying_identical_plugin_entry_twice_does_not_duplicate(self, tmp_path: Path) -> None:
        project_root = _project(tmp_path)
        config_path = project_root / ".opencode" / "opencode.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({"plugin": []}), encoding="utf-8")

        request = PluginEntryRequest(entry_id="@ma34/dup", ownership_scope="ma34-dup-test")
        manage_plugin_entry(project_root, "opencode", mode="apply", request=request)
        manage_plugin_entry(project_root, "opencode", mode="apply", request=request)

        raw = json.loads(config_path.read_text(encoding="utf-8"))
        matches = [
            entry
            for entry in raw["plugin"]
            if (entry[0] if isinstance(entry, list) else entry) == "@ma34/dup"
        ]
        assert len(matches) == 1, f"expected exactly one entry, found {len(matches)}"

    # test_removing_nonexistent_mcp_server_is_a_safe_noop is now covered,
    # for every mcp_config provider, by
    # TestMcpConfigAcrossAllHarnesses.test_purge_is_idempotent.

    def test_removing_nonexistent_hook_is_a_safe_noop(self, tmp_path: Path, monkeypatch) -> None:
        _isolated_home(tmp_path, monkeypatch)
        project_root = _project(tmp_path)

        request = ManagedHooksRequest(ownership_scope="ma34-missing-test", entries=())
        result = manage_hook_entries(project_root, "codex", mode="prune", request=request)
        assert result.ok
        assert result.removed_ids == ()
