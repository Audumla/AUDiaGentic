"""Install command implementation."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from audiagentic.foundation.cli_io import print_message
from audiagentic.foundation.components.ids import COMPONENT_SESSION
from audiagentic.foundation.paths.home import global_harness_runtime
from audiagentic.runtime.harness import install_to

logger = logging.getLogger(__name__)


def _cmd_install(target: Path, project_root: Path) -> int:
    print_message(f"Installing AUDiaGentic harness into {target}")
    rc = install_to(target, project_root=project_root)
    if not rc:
        try:
            from audiagentic.foundation.components.loader import register_all_components
            from audiagentic.foundation.lifecycle.components import install_component
            register_all_components()
            install_component(COMPONENT_SESSION, project_root)
        except Exception:
            logger.warning("Failed to auto-install session component", exc_info=True)
        print_message("\nInstall complete. Run 'audiagentic' from any project directory.")
        if target != global_harness_runtime():
            print_message(f"Set AUDIAGENTIC_HOME={target.parent} to use this location.")
    return rc


def cmd_install(args: argparse.Namespace, project_root: Path) -> int:
    target = Path(args.target).resolve() if args.target else global_harness_runtime()
    return _cmd_install(target, project_root)
