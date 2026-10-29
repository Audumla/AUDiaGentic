"""Read-only gpt-auto availability: is the configured CDP browser reachable?"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from audiagentic.components.providers.services.config.provider_config import load_provider_config

from .config import GptAutoConfig


def cdp_availability(project_root: Path | None, provider_id: str = "gpt-auto", *, timeout: float = 3.0) -> tuple[bool, str]:
    """Probe ``<cdp.endpoint>/json/version`` with the config dispatch would use."""
    overlay: dict = {}
    if project_root is not None:
        providers = load_provider_config(project_root).get("providers") or {}
        candidate = providers.get(provider_id) or providers.get("gpt-auto")
        overlay = candidate if isinstance(candidate, dict) else {}
    endpoint = GptAutoConfig.from_project_dict(overlay).cdp.endpoint.rstrip("/")
    try:
        with urllib.request.urlopen(f"{endpoint}/json/version", timeout=timeout) as response:
            browser = json.loads(response.read().decode("utf-8")).get("Browser", "browser")
    except (OSError, urllib.error.URLError, ValueError) as error:
        return False, f"CDP endpoint {endpoint} is not reachable ({error})"
    return True, f"CDP endpoint {endpoint} answers ({browser})"
