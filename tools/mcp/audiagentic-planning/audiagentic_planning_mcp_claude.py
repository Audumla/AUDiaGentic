#!/usr/bin/env python3
"""Redirect shim — consolidated server is now audiagentic-planning_mcp.py.

This file is kept so existing MCP configs that reference it continue to work.
It simply delegates to the canonical server file.
"""
import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).parent / "audiagentic-planning_mcp.py"),
    run_name="__main__",
)
