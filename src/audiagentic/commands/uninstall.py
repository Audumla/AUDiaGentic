"""Public harness uninstall command."""
from __future__ import annotations

import argparse
from pathlib import Path

from audiagentic.foundation.cli_io import print_message
from audiagentic.foundation.paths.home import global_harness_runtime
from audiagentic.runtime.harness import uninstall_from


def cmd_uninstall(args: argparse.Namespace, _project_root: Path) -> int:
    """Remove harness-owned runtime files while preserving user assets."""
    target = Path(args.target).resolve() if args.target else global_harness_runtime()
    print_message(f"Uninstalling AUDiaGentic harness from {target}")
    return uninstall_from(target)
