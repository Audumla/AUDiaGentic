from __future__ import annotations

import json
import re
from pathlib import Path


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
        from audiagentic.components.optional.providers.services.lifecycle import (
            reconcile_all_providers,
            reconcile_provider,
        )

        def _progress(event) -> None:
            message = getattr(event, "message", str(event))
            print(message, flush=True)

        if reconcile_all_match:
            result = reconcile_all_providers(project_root=project_root, on_progress=_progress)
        else:
            result = reconcile_provider(reconcile_one_match.group(1).lower(), project_root=project_root, on_progress=_progress)

        print(json.dumps(result, indent=2), flush=True)
        return 0 if result.get("ok", True) else 1

    match = re.fullmatch(
        r"\s*(install|uninstall|repair)\s+(?:the\s+)?([a-z0-9_.-]+)(?:\s+(?:provider|provider\s+cli))?\s*",
        prompt,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    action = match.group(1).lower()
    provider_id = match.group(2).lower()

    from audiagentic.components.optional.providers.services.lifecycle import (
        install_provider_cli,
        repair_provider_cli,
        uninstall_provider_cli,
    )

    handlers = {
        "install": install_provider_cli,
        "uninstall": uninstall_provider_cli,
        "repair": repair_provider_cli,
    }

    def _progress(event) -> None:
        message = getattr(event, "message", str(event))
        print(f"[{provider_id}] {message}", flush=True)

    result = handlers[action](
        provider_id,
        dry_run=False,
        project_root=project_root,
        on_progress=_progress,
    )
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result.get("status") in {"installed", "uninstalled", "repaired", "skipped"} else 1
