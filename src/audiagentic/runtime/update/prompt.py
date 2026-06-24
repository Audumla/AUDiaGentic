"""Interactive update prompt for the audiagentic CLI."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from audiagentic.cli_io import print_message

from .checker import check_update, current_version, record_failed_install, skip_version
from .runner import install_version

logger = logging.getLogger(__name__)


def _handle_install_result(result: dict, version: str) -> tuple[int, bool]:
    """Handle install result and return (exit_code, should_exit)."""
    if result.get("ok") == "scheduled":
        print_message(f"\n  Closing audiagentic — update to {version} will install in the new window.\n")
        return 0, True
    if result.get("ok"):
        print_message(f"\n  Updated to {version}. Restart audiagentic to use the new version.\n")
        return 0, True
    print_message(f"\n  Update failed: {result.get('error')}")
    return 1, False


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
    print_message(f"\n  audiagentic {latest} available  (installed: {current})")
    answer = _ask("  Update now? [y/N/s=skip this version] ")
    if answer in ("y", "yes"):
        return "yes"
    if answer in ("s", "skip"):
        return "skip"
    return "no"


def maybe_prompt_update(project_root: Path | None = None) -> None:
    """Check for an update and prompt if running interactively.

    Called at launch when auto-update is enabled via AUDIAGENTIC_AUTO_UPDATE_ENABLED.
    Silent when stdout is not a TTY (pipes, CI, subprocess).
    Never raises — update failures must not prevent the agent from starting.
    """
    if not sys.stdout.isatty():
        return
    try:
        info = check_update()
        if not info:
            return
        answer = prompt_update(info)
        if answer == "skip":
            skip_version(info["latest"])
            return
        if answer == "yes":
            result = install_version(info["latest"])
            exit_code, should_exit = _handle_install_result(result, info["latest"])
            if should_exit:
                sys.exit(0)
            record_failed_install(info["latest"])
            if not result.get("locked"):
                print_message(f"\n  Update failed: {result.get('error')}. Continuing with current version.\n")
    except Exception:
        logger.warning("Update failed unexpectedly", exc_info=True)


def run_update_now() -> int:
    """Explicit update — bypass cache, always prompt, used by `audiagentic update` command."""
    try:
        info = check_update(force=True)
        if not info:
            print_message(f"Already up to date (version {current_version()}).")
            return 0
        answer = prompt_update(info)
        if answer == "skip":
            skip_version(info["latest"])
            print_message("Version skipped.")
            return 0
        if answer == "yes":
            result = install_version(info["latest"])
            exit_code, should_exit = _handle_install_result(result, info["latest"])
            if should_exit:
                sys.exit(0)
            return exit_code
        print_message("Update cancelled.")
        return 0
    except Exception as exc:  # noqa: BLE001
        print_message(f"Update check failed: {exc}")
        return 1
