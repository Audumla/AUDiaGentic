"""In-container smoke test: build every AUDiaGentic MCP server, list tools,
and execute read-only no-arg tools. Empty/not-installed results count as pass;
only raised exceptions are failures. Exit non-zero if any server errors."""
from __future__ import annotations

import asyncio
import importlib
import os
import sys

os.environ.setdefault("AUDIAGENTIC_REPO_ROOT", "/app")

# (label, module, "build"|None=use .mcp, [read-only no-arg tools to execute])
SERVERS = [
    ("project-manage", "audiagentic.components.project.project_mcp", "build", ["list_components", "project_status"]),
    ("session-manage", "audiagentic.components.session.session_mcp", "build", ["config", "cli_visibility"]),
    ("ledger-write", "audiagentic.components.ledger.ledger_mcp", None, ["get_current_summary"]),
    ("ledger-manage", "audiagentic.components.ledger.ledger_manage_mcp", None, ["get_ledger_status"]),
    ("lsp", "audiagentic.components.coding_lsp.lsp_mcp", None, []),
    ("lsp-manage", "audiagentic.components.coding_lsp.lsp_manage_mcp", None, ["lsp_config_status", "lsp_list_languages", "lsp_list_missing"]),
    ("providers-manage", "audiagentic.components.providers.providers_mcp", "build", ["list_providers", "list_provider_descriptors"]),
    ("source-control", "audiagentic.components.source_control.source_control_mcp", None, ["get_source_control_status"]),
    ("release-manage", "audiagentic.components.release.release_mcp", None, ["get_release_status"]),
    ("release-please", "audiagentic.components.release.release_please.release_please_mcp", None, []),
]


async def get_mcp(mod, how):
    m = importlib.import_module(mod)
    return m.build_server() if how == "build" else m.mcp


async def main() -> int:
    failures = 0
    for label, mod, how, calls in SERVERS:
        try:
            mcp = await get_mcp(mod, how)
            tools = await mcp.list_tools()
            names = [t.name for t in tools]
            print(f"[OK ] {label:<16} {len(names)} tools")
            for c in calls:
                if c not in names:
                    print(f"        - {c}: SKIP (not registered)")
                    continue
                try:
                    await mcp.call_tool(c, {})
                    print(f"        - {c}: ok")
                except Exception as e:  # noqa: BLE001
                    failures += 1
                    print(f"        - {c}: FAIL {type(e).__name__}: {str(e)[:120]}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"[ERR] {label:<16} {type(e).__name__}: {str(e)[:160]}")
    print(f"\n=== {'ALL PASS' if failures == 0 else f'{failures} FAILURE(S)'} ===")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
