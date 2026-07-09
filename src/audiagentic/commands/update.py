"""Update command implementation."""
from __future__ import annotations

import argparse
from pathlib import Path


def cmd_update(args: argparse.Namespace, project_root: Path) -> int:
    del args, project_root
    from audiagentic.runtime.update.prompt import run_update_now
    return run_update_now()
