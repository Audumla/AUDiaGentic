#!/usr/bin/env python3
"""Project-local launcher for the AUDiaGentic planning MCP server.

This wrapper keeps the MCP config project-specific and portable by resolving the
repository root from this file location at runtime instead of depending on the
client's process cwd.
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def main() -> None:
    here = Path(__file__).resolve()
    project_root = here.parents[3]
    target_root = Path(os.environ.get("AUDIAGENTIC_ROOT", project_root)).resolve()
    os.environ["AUDIAGENTIC_ROOT"] = str(target_root)
    os.chdir(project_root)

    for candidate in (project_root, project_root / "src"):
        value = str(candidate)
        if value not in sys.path:
            sys.path.insert(0, value)

    server_path = project_root / "tools" / "mcp" / "audiagentic-planning" / "audiagentic-planning_mcp.py"
    runpy.run_path(str(server_path), run_name="__main__")


if __name__ == "__main__":
    main()
