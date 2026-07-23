"""Private process-entry handlers used by generated harness configuration."""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error


def cmd_mcp(args: argparse.Namespace, project_root: Path) -> int:
    """Run a configured component MCP module over stdio.

    This is intentionally an internal launcher contract: generated MCP config
    invokes it, but it is not part of the supported interactive CLI surface.
    """
    del project_root
    module = importlib.import_module(args.module)
    main = getattr(module, "main", None)
    if not callable(main):
        raise make_error(
            prefix="CFG",
            component="MCP",
            number=2,
            kind="mcp",
            message="MCP module does not expose a callable main().",
            details={"module": args.module},
        )
    original_argv = sys.argv
    try:
        sys.argv = [args.module, *(args.module_args or [])]
        result = main()
    finally:
        sys.argv = original_argv
    return result if isinstance(result, int) else 0
