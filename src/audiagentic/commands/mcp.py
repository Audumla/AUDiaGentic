"""MCP server command implementation."""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError


def cmd_mcp(
    module_name_or_args: str | argparse.Namespace,
    module_args_or_project_root: list[str] | Path = [],
) -> int:
    if isinstance(module_name_or_args, str):
        module_name = module_name_or_args
        module_args = module_args_or_project_root if isinstance(module_args_or_project_root, list) else []
    else:
        args = module_name_or_args
        project_root = module_args_or_project_root
        del project_root
        module_name = args.module
        module_args = args.module_args or []
    module = importlib.import_module(module_name)
    main_fn = getattr(module, "main", None)
    if not callable(main_fn):
        raise AudiaGenticError(
            code="CFG-MCP-002",
            kind="mcp",
            message="MCP module does not expose a callable main()",
            details={"module": module_name},
        )
    old_argv = sys.argv
    try:
        sys.argv = [module_name, *module_args]
        result = main_fn()
    finally:
        sys.argv = old_argv
    return result if isinstance(result, int) else 0
