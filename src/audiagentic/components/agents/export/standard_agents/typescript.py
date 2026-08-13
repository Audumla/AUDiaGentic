"""Stable TypeScript build output for a Standard Agents projection."""
from __future__ import annotations

import json


def render_typescript(agent: dict) -> str:
    payload = json.dumps(agent, sort_keys=True, indent=2, ensure_ascii=False)
    return "import { defineAgent } from '@standard-agents/sdk';\n\nexport default defineAgent(" + payload + ");\n"
