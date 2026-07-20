"""Codex hooks.json format handlers.

Presents ~/.codex/hooks.json as a NAME-KEYED dict where key = command string,
value = {event, timeout}. The adapter is the ONLY place that knows Codex's
nested per-event list shape (entries are {type:"command", command, timeout}
under event keys; 'type' stays adapter-internal).

Also carries the surgical [features] hooks upsert — enables the flag
when writing entries.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.io import atomic_write_text

_hooks_error = make_error_factory("CFG", "CDXHK", "providers-codex")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _load_hooks(path: Path) -> dict[str, Any]:
    """Missing hooks.json returns {}; malformed content raises instead of
    being silently treated the same as absent (RV713) — the next managed
    write would otherwise overwrite and discard whatever was on disk."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise _hooks_error(1, f"Invalid Codex hooks.json: {path}", path=str(path)) from exc


def _save_hooks(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(data, indent=2) + "\n")


def _find_command_in_event(
    hooks_list: list[dict[str, Any]], command: str
) -> tuple[int | None, int | None]:
    """Return (outer_index, inner_index) of the matching command entry, or (None, None)."""
    for i, group in enumerate(hooks_list):
        for j, hook in enumerate(group.get("hooks", [])):
            if hook.get("command") == command:
                return (i, j)
    return (None, None)


def _remove_command_from_data(data: dict[str, Any], command: str) -> bool:
    """Remove the first matching command entry from any event. Returns True if removed."""
    hooks_section = data.get("hooks", {})
    if not isinstance(hooks_section, dict):
        return False

    for event_key, hooks_list in list(hooks_section.items()):
        if not isinstance(hooks_list, list):
            continue
        outer_idx, inner_idx = _find_command_in_event(hooks_list, command)
        if outer_idx is not None and inner_idx is not None:
            group_hooks = hooks_list[outer_idx].get("hooks", [])
            group_hooks.pop(inner_idx)
            if not group_hooks:
                hooks_list.pop(outer_idx)
            if not hooks_list:
                hooks_section.pop(event_key)
            return True
    return False


# RS18/RS06: intentional one-off — surgical TOML editing to upsert [features] section.
# Not expressible via WriteFileStep because the file is not owned by this recipe
# (shared with other codex settings); only a single key must be patched, not rewritten.
def _enable_codex_hooks(config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    text = _read_text(config_path)
    lines = text.splitlines()
    if not lines:
        atomic_write_text(config_path, "[features]\nhooks = true\n")
        return

    in_features = False
    has_current_flag = False
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_features = stripped == "[features]"
            continue
        key = stripped.partition("=")[0].strip()
        if in_features and key == "hooks":
            has_current_flag = True

    out: list[str] = []
    in_features = False
    saw_features = False
    wrote = False
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_features and not wrote:
                out.append("hooks = true")
                wrote = True
            in_features = stripped == "[features]"
            saw_features = saw_features or in_features
            out.append(raw)
            continue
        key = stripped.partition("=")[0].strip()
        if in_features and key == "codex_hooks":
            if not has_current_flag and not wrote:
                out.append("hooks = true")
                wrote = True
            continue
        if in_features and key == "hooks":
            out.append("hooks = true")
            wrote = True
            continue
        out.append(raw)

    if saw_features and in_features and not wrote:
        out.append("hooks = true")
        wrote = True
    if not saw_features:
        if out and out[-1].strip():
            out.append("")
        out.extend(["[features]", "hooks = true"])
    atomic_write_text(config_path, "\n".join(out).rstrip() + "\n")


def read_codex_hooks(path: Path) -> dict[str, dict[str, Any]]:
    """Read hooks.json and return a NAME-KEYED dict.

    Key = command string, value = {event, timeout}.
    Only entries with type "command" are included; 'type' is adapter-internal.
    """
    data = _load_hooks(path)
    hooks_section = data.get("hooks", {})
    if not isinstance(hooks_section, dict):
        return {}

    result: dict[str, dict[str, Any]] = {}
    for event_key, hooks_list in hooks_section.items():
        if not isinstance(hooks_list, list):
            continue
        for group in hooks_list:
            for hook in group.get("hooks", []):
                if not isinstance(hook, dict):
                    continue
                if hook.get("type") != "command":
                    continue
                command = hook.get("command")
                if not command:
                    continue
                result[command] = {
                    "event": event_key,
                    "timeout": hook.get("timeout"),
                }
    return result


def write_codex_hooks(path: Path, entries: dict[str, dict[str, Any]]) -> None:
    """Write one or more hook entries into hooks.json.

    Merges with existing content — foreign entries are preserved. Enables the
    [features] hooks = true flag in ~/.codex/config.toml so Codex will
    actually run hooks (decision (a) of MA26 step 3).
    """
    data = _load_hooks(path)
    hooks_section = data.setdefault("hooks", {})
    if not isinstance(hooks_section, dict):
        hooks_section = {}
        data["hooks"] = hooks_section

    for command, value in entries.items():
        event_key = value.get("event", "SessionStart")
        timeout = value.get("timeout")

        # Remove existing entry with this command from any event (rename case)
        _remove_command_from_data(data, command)

        # Add to the correct event
        if event_key not in hooks_section:
            hooks_section[event_key] = []

        hooks_list = hooks_section[event_key]
        hook_entry: dict[str, Any] = {"type": "command", "command": command}
        if timeout is not None:
            hook_entry["timeout"] = timeout
        hooks_list.append({"hooks": [hook_entry]})

    _save_hooks(path, data)
    _enable_codex_hooks(Path.home() / ".codex" / "config.toml")


def remove_codex_hook(path: Path, name: str) -> bool:
    """Remove a single hook entry by command string.

    Returns True if the entry was found and removed. Preserves all foreign
    entries in the file — never unlinks the file while foreign entries remain.
    """
    if not path.exists():
        return False
    data = _load_hooks(path)
    removed = _remove_command_from_data(data, name)
    if removed:
        hooks_section = data.get("hooks", {})
        if hooks_section and isinstance(hooks_section, dict):
            _save_hooks(path, data)
        else:
            path.unlink(missing_ok=True)
    return removed
