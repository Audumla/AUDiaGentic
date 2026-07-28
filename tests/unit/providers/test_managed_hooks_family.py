"""MA26 managed-hooks family tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from audiagentic.components.providers.adapters.codex import hooks_format
from audiagentic.components.providers.contracts.managed_hooks import (
    ManagedHooksEntry,
    ManagedHooksRequest,
)
from audiagentic.components.providers.services.capabilities import managed_hooks_family as family
from audiagentic.foundation.toolchains.config.managed_config import ManagedConfigSpec


def _capability(**overrides: object) -> SimpleNamespace:
    values = {
        "payload_contract": "provider-managed-hooks-payload/v1",
        "result_contract": "provider-managed-hooks-result/v1",
        "supported_modes": ("apply", "prune", "status"),
        "ownership_scope_required": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _descriptor(hooks_file: Path, *, capability: SimpleNamespace | None = None) -> SimpleNamespace:
    cap = capability or _capability()
    return SimpleNamespace(
        hooks_config=ManagedConfigSpec(
            config_path=str(hooks_file),
            reader=hooks_format.read_codex_hooks,
            writer=hooks_format.write_codex_hooks,
            remover=hooks_format.remove_codex_hook,
            format="codex-hooks-json",
            refresh_mode="restart-required",
        ),
        automation_capability=lambda family_id: cap if family_id == "managed-hooks" else None,
    )


def _write_nested_hooks(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "foreign-session-start",
                                    "timeout": 10,
                                }
                            ]
                        }
                    ],
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "foreign-stop",
                                    "timeout": 30,
                                }
                            ]
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )


def _commands_by_event(path: Path) -> dict[str, set[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, set[str]] = {}
    for event, groups in payload.get("hooks", {}).items():
        result[event] = {
            hook["command"]
            for group in groups
            for hook in group.get("hooks", [])
            if hook.get("type") == "command"
        }
    return result


def test_foreign_nested_codex_hooks_survive_apply_and_prune(monkeypatch, tmp_path):
    """Foreign hooks, including one under the same event, survive apply and prune."""
    hooks_file = tmp_path / ".codex" / "hooks.json"
    _write_nested_hooks(hooks_file)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(family, "get_descriptor", lambda _pid: _descriptor(hooks_file))

    apply_request = ManagedHooksRequest(
        ownership_scope="hindsight",
        entries=(
            ManagedHooksEntry(
                managed_id="hindsight/session-start",
                event="SessionStart",
                command="python scripts/session_start.py",
                timeout=5,
            ),
        ),
    )

    result_apply = family.manage_hook_entries(
        tmp_path, "codex", mode="apply", request=apply_request
    )
    assert result_apply.ok is True
    assert result_apply.changed is True
    assert result_apply.managed_ids == ("hindsight/session-start",)

    after_apply = _commands_by_event(hooks_file)
    assert after_apply["SessionStart"] == {
        "foreign-session-start",
        "python scripts/session_start.py",
    }
    assert after_apply["Stop"] == {"foreign-stop"}
    assert (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8") == (
        "[features]\nhooks = true\n"
    )

    result_prune = family.manage_hook_entries(
        tmp_path,
        "codex",
        mode="prune",
        request=ManagedHooksRequest(ownership_scope="hindsight"),
    )
    assert result_prune.ok is True
    assert result_prune.changed is True
    assert result_prune.managed_ids == ()
    assert result_prune.removed_ids == ("hindsight/session-start",)

    assert hooks_file.exists()
    after_prune = _commands_by_event(hooks_file)
    assert after_prune["SessionStart"] == {"foreign-session-start"}
    assert after_prune["Stop"] == {"foreign-stop"}


def test_codex_hook_enable_migrates_deprecated_feature_key(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        'model = "gpt-test"\n\n[features]\ncodex_hooks = true\nforeign = true\n',
        encoding="utf-8",
    )

    hooks_format._enable_codex_hooks(config_path)

    assert config_path.read_text(encoding="utf-8") == (
        'model = "gpt-test"\n\n[features]\nhooks = true\nforeign = true\n'
    )


def test_codex_hook_enable_removes_legacy_key_when_current_key_exists(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[features]\ncodex_hooks = true\nhooks = false\nforeign = true\n",
        encoding="utf-8",
    )

    hooks_format._enable_codex_hooks(config_path)

    assert config_path.read_text(encoding="utf-8") == ("[features]\nhooks = true\nforeign = true\n")


def test_status_reports_registered_managed_hook_ids(monkeypatch, tmp_path):
    hooks_file = tmp_path / ".codex" / "hooks.json"
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(family, "get_descriptor", lambda _pid: _descriptor(hooks_file))

    family.manage_hook_entries(
        tmp_path,
        "codex",
        mode="apply",
        request=ManagedHooksRequest(
            ownership_scope="hindsight",
            entries=(
                ManagedHooksEntry(
                    managed_id="hindsight/recall",
                    event="UserPromptSubmit",
                    command="python scripts/recall.py",
                    timeout=12,
                ),
            ),
        ),
    )

    result = family.manage_hook_entries(
        tmp_path,
        "codex",
        mode="status",
        request=ManagedHooksRequest(ownership_scope="hindsight"),
    )

    assert result.ok is True
    assert result.managed_ids == ("hindsight/recall",)


def test_descriptor_declaration_must_match_family_pin(monkeypatch, tmp_path):
    hooks_file = tmp_path / ".codex" / "hooks.json"
    wrong_capability = _capability(supported_modes=("apply", "status"))
    monkeypatch.setattr(
        family,
        "get_descriptor",
        lambda _pid: _descriptor(hooks_file, capability=wrong_capability),
    )

    result = family.manage_hook_entries(
        tmp_path,
        "codex",
        mode="apply",
        request=ManagedHooksRequest(ownership_scope="hindsight"),
    )

    assert result.ok is False
    assert result.supported is True
    assert result.error_code == "VAL-PHKS-001"


def test_managed_hooks_provider_source_is_requester_blind():
    """Provider managed-hooks source must not reference Hindsight or Vectorize."""
    repo_root = Path(__file__).resolve().parents[3]
    source_files = [
        repo_root
        / "src"
        / "audiagentic"
        / "components"
        / "providers"
        / "contracts"
        / "managed_hooks.py",
        repo_root
        / "src"
        / "audiagentic"
        / "components"
        / "providers"
        / "services"
        / "capabilities"
        / "managed_hooks_family.py",
        repo_root
        / "src"
        / "audiagentic"
        / "components"
        / "providers"
        / "adapters"
        / "codex"
        / "hooks_format.py",
    ]

    hits: list[str] = []
    for source_file in source_files:
        for line_number, line in enumerate(source_file.read_text(encoding="utf-8").splitlines(), 1):
            lowered = line.lower()
            if "hindsight" in lowered or "vectorize" in lowered:
                rel = source_file.relative_to(repo_root)
                hits.append(f"{rel}:{line_number}: {line.strip()}")

    assert hits == []
