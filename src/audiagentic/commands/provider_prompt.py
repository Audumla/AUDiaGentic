from __future__ import annotations

import re
from pathlib import Path

from audiagentic.foundation.cli_io import print_error, print_json


def _try_provider_prompt(prompt: str | None, project_root: Path) -> int | None:
    """Handle unambiguous provider lifecycle prompts directly with live output.

    Pi's MCP adapter does not surface MCP log notifications in non-interactive
    prompt mode, so direct lifecycle prompts need to bypass the agent to provide
    user-visible streaming while still using the provider component backend.
    """
    if not prompt:
        return None

    reconcile_all_match = re.fullmatch(
        r"\s*reconcile\s+(?:all\s+)?(?:providers?|provider\s+clis?)\s*",
        prompt,
        flags=re.IGNORECASE,
    )
    reconcile_one_match = re.fullmatch(
        r"\s*reconcile\s+([a-z0-9_.-]+)(?:\s+(?:provider|provider\s+cli))?\s*",
        prompt,
        flags=re.IGNORECASE,
    )
    if reconcile_all_match or reconcile_one_match:
        from audiagentic.foundation.components.registry import get_descriptor

        if not get_descriptor("providers"):
            print_error("providers component not available")
            return 1

        from audiagentic.components.providers.services.lifecycle import (
            reconcile_all_providers,
            reconcile_provider,
        )

        if reconcile_all_match:
            result = reconcile_all_providers(project_root=project_root)
        elif reconcile_one_match:
            result = reconcile_provider(reconcile_one_match.group(1).lower(), project_root=project_root)
        else:
            print_error("providers component not available")
            return 1

        print_json(result)
        return 0 if result.get("ok", True) else 1

    match = re.fullmatch(
        r"\s*(install|uninstall|repair)\s+(?:the\s+)?([a-z0-9_.-]+)(?:\s+(?:provider|provider\s+cli))\s*",
        prompt,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    action = match.group(1).lower()
    provider_id = match.group(2).lower()

    from audiagentic.foundation.components.registry import (
        get_descriptor as _get_component_descriptor,
    )

    if not _get_component_descriptor("providers"):
        print_error("providers component not available")
        return 1

    from typing import cast

    from audiagentic.components.providers.contracts.cli_lifecycle import CliLifecycleMode

    mode_map = {
        "install": "apply",
        "uninstall": "prune",
        "repair": "apply",
    }
    mode = cast(CliLifecycleMode, mode_map[action])

    import asyncio

    from audiagentic.components.providers import providers_api

    result = asyncio.run(
        providers_api.manage_cli_lifecycle(project_root, provider_id, mode=mode)
    )
    print_json(result)
    return 0 if result.get("ok") else 1
