"""Interactive update prompt for the audiagentic CLI."""
from __future__ import annotations

import sys
from pathlib import Path


def _ask(question: str) -> str:
    """Read a line from stdin, returning empty string on EOF/interrupt."""
    try:
        return input(question).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return ""


def prompt_update(info: dict) -> str:
    """Show the update prompt. Returns 'yes', 'no', or 'skip'."""
    latest = info["latest"]
    current = info["current"]
    print(f"\n  audiagentic {latest} available  (installed: {current})")
    answer = _ask("  Update now? [y/N/s=skip this version] ")
    if answer in ("y", "yes"):
        return "yes"
    if answer in ("s", "skip"):
        return "skip"
    return "no"


def maybe_prompt_update(project_root: Path | None = None) -> None:
    """Check for an update and prompt if running interactively.

    Called at launch when the auto-update harness component is installed and enabled.
    Silent when stdout is not a TTY (pipes, CI, subprocess).
    Never raises — update failures must not prevent the agent from starting.
    """
    if not sys.stdout.isatty():
        return
    try:
        from .checker import check_update, skip_version
        info = check_update()
        if not info:
            return
        answer = prompt_update(info)
        if answer == "skip":
            skip_version(info["latest"])
            return
        if answer == "yes":
            from .runner import install_version
            result = install_version(info["latest"])
            if result.get("ok") == "scheduled":
                print(f"\n  Closing audiagentic — update to {info['latest']} will install in the new window.\n")
                sys.exit(0)
            elif result.get("ok"):
                print(f"\n  Updated to {info['latest']}. Restart audiagentic to use the new version.\n")
                sys.exit(0)
            elif not result.get("locked"):
                print(f"\n  Update failed: {result.get('error')}. Continuing with current version.\n")
    except Exception:  # noqa: BLE001
        pass


def run_update_now() -> int:
    """Explicit update — bypass cache, always prompt, used by `audiagentic update` command."""
    try:
        from .checker import check_update, current_version
        info = check_update(force=True)
        if not info:
            print(f"Already up to date (version {current_version()}).")
            return 0
        answer = prompt_update(info)
        if answer == "skip":
            from .checker import skip_version
            skip_version(info["latest"])
            print("Version skipped.")
            return 0
        if answer == "yes":
            from .runner import install_version
            result = install_version(info["latest"])
            if result.get("ok") == "scheduled":
                print(f"\nClosing audiagentic — update to {info['latest']} will install in the new window.")
                sys.exit(0)
            elif result.get("ok"):
                print(f"\nUpdated to {info['latest']}. Restart audiagentic to use the new version.")
                return 0
            else:
                print(f"\nUpdate failed: {result.get('error')}")
                return 1
        print("Update cancelled.")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Update check failed: {exc}")
        return 1
