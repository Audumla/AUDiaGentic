"""MA26 step 5 — Preservation regression test.

A foreign hook (including one on the same event as ours) must survive
apply AND prune. Prune removes only owned entries and leaves the file
while foreign entries remain. The engine (reconcile_fragments via
sync_managed_config) already does this; we verify it does not regress.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from audiagentic.components.providers.contracts.managed_hooks import (
    ManagedHooksEntry,
    ManagedHooksRequest,
)
from audiagentic.components.providers.services import managed_hooks_family as family


def _descriptor():
    return SimpleNamespace(
        hooks_config=SimpleNamespace(
            config_path=lambda project_root: Path.home() / ".codex" / "hooks.json",
            reader=lambda path: json.loads(path.read_text()) if path.exists() else {},
            writer=lambda path, entries: _write_hooks(path, entries),
            remover=lambda path, name: _remove_hook(path, name),
            format="codex-hooks-json",
            refresh_mode="restart-required",
            reload_fn=None,
            capabilities=frozenset(),
        ),
        automation_capability=lambda family_id: object()
        if family_id == "managed-hooks"
        else None,
    )


def _read_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _write_hooks(path, entries):
    """Write entries as flat command-keyed dict to hooks.json."""
    data = json.loads(_read_text(path)) if _read_text(path) else {}
    for cmd, value in entries.items():
        data[cmd] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _remove_hook(path, name):
    if not path.exists():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    if name in data:
        del data[name]
        if data:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        else:
            path.unlink(missing_ok=True)
        return True
    return False


def test_foreign_hook_survives_apply_and_prune(monkeypatch, tmp_path):
    """A foreign hook on the SAME event survives apply AND prune."""
    monkeypatch.setattr(family, "get_descriptor", lambda _pid: _descriptor())

    hooks_file = tmp_path / ".codex" / "hooks.json"
    hooks_file.parent.mkdir(parents=True, exist_ok=True)

    # Pre-populate with a foreign hook on SessionStart (same event as ours)
    foreign_data = {
        "my-foreign-command": {"event": "SessionStart", "timeout": 10}
    }
    hooks_file.write_text(json.dumps(foreign_data), encoding="utf-8")

    # Override config_path to use our test directory
    desc = _descriptor()
    desc.hooks_config.config_path = hooks_file
    monkeypatch.setattr(family, "get_descriptor", lambda _pid: desc)

    # Apply our owned entry on the SAME event
    apply_request = ManagedHooksRequest(
        ownership_scope="hindsight",
        entries=(ManagedHooksEntry(
            managed_id="hindsight/session-start",
            event="SessionStart",
            command='python scripts/session_start.py',
            timeout=5,
        ),),
    )

    # Monkeypatch the registry to use our tmp_path
    def _test_registry(project_root):
        from audiagentic.foundation.toolchains.managed_config import ManagedFragmentRegistry
        return ManagedFragmentRegistry(
            project_root, "managed-hooks.json", top_level_key="providers"
        )

    monkeypatch.setattr(family, "_hooks_ownership_registry", _test_registry)

    result_apply = family.manage_hook_entries(
        tmp_path, "codex", mode="apply", request=apply_request
    )
    assert result_apply.ok is True
    assert result_apply.changed is True

    # Both foreign and owned entries exist after apply
    data_after_apply = json.loads(hooks_file.read_text(encoding="utf-8"))
    assert "my-foreign-command" in data_after_apply, "Foreign hook was destroyed by apply!"
    assert 'python scripts/session_start.py' in data_after_apply, "Owned hook not written"

    # Prune our owned entry
    prune_request = ManagedHooksRequest(ownership_scope="hindsight")
    result_prune = family.manage_hook_entries(
        tmp_path, "codex", mode="prune", request=prune_request
    )
    assert result_prune.ok is True

    # Foreign hook survives prune; file still exists
    data_after_prune = json.loads(hooks_file.read_text(encoding="utf-8"))
    assert "my-foreign-command" in data_after_prune, "Foreign hook was destroyed by prune!"
    assert 'python scripts/session_start.py' not in data_after_prune, "Owned hook not pruned"


def test_prune_leaves_file_with_foreign_entries(monkeypatch, tmp_path):
    """Prune removes only owned entries; file remains while foreign entries exist."""
    monkeypatch.setattr(family, "get_descriptor", lambda _pid: _descriptor())

    hooks_file = tmp_path / ".codex" / "hooks.json"
    hooks_file.parent.mkdir(parents=True, exist_ok=True)

    # Pre-populate with both foreign and owned entries
    initial_data = {
        "foreign-cmd": {"event": "SessionStart", "timeout": 10},
        'python scripts/session_start.py': {"event": "SessionStart", "timeout": 5},
    }
    hooks_file.write_text(json.dumps(initial_data), encoding="utf-8")

    desc = _descriptor()
    desc.hooks_config.config_path = hooks_file
    monkeypatch.setattr(family, "get_descriptor", lambda _pid: desc)

    # Seed the registry so our entry is owned
    from audiagentic.foundation.toolchains.managed_config import ManagedFragmentRegistry

    def _test_registry(project_root):
        return ManagedFragmentRegistry(
            project_root, "managed-hooks.json", top_level_key="providers"
        )

    monkeypatch.setattr(family, "_hooks_ownership_registry", _test_registry)

    # First apply to register ownership
    apply_request = ManagedHooksRequest(
        ownership_scope="hindsight",
        entries=(ManagedHooksEntry(
            managed_id="hindsight/session-start",
            event="SessionStart",
            command='python scripts/session_start.py',
            timeout=5,
        ),),
    )
    family.manage_hook_entries(tmp_path, "codex", mode="apply", request=apply_request)

    # Prune
    prune_request = ManagedHooksRequest(ownership_scope="hindsight")
    result_prune = family.manage_hook_entries(
        tmp_path, "codex", mode="prune", request=prune_request
    )
    assert result_prune.ok is True

    # File still exists with only the foreign entry
    assert hooks_file.exists(), "File was unlinked while foreign entries remain!"
    data_after = json.loads(hooks_file.read_text(encoding="utf-8"))
    assert "foreign-cmd" in data_after
    assert 'python scripts/session_start.py' not in data_after


def test_managed_hooks_no_hindsight_reference():
    """MA26 step 4 files must not reference Hindsight or Vectorize."""
    import re

    repo_root = Path(__file__).resolve().parents[3]
    new_files = [
        repo_root / "src" / "audiagentic" / "components" / "providers" / "contracts" / "managed_hooks.py",
        repo_root / "src" / "audiagentic" / "components" / "providers" / "services" / "managed_hooks_family.py",
        repo_root / "src" / "audiagentic" / "components" / "providers" / "adapters" / "codex" / "hooks_format.py",
    ]
    pattern = re.compile(r"(?i)hindsight|vectorize")

    hits: list[str] = []
    for py_file in new_files:
        content = py_file.read_text(encoding="utf-8")
        for i, line in enumerate(content.splitlines(), 1):
            if pattern.search(line):
                rel = str(py_file.relative_to(repo_root))
                hits.append(f"{rel}:{i}: {line.strip()}")

    assert not hits, (
        "Requester-blindness violated in MA26 files — found Hindsight references:\n" + "\n".join(hits)
    )
