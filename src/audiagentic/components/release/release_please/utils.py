"""Utility functions for release-please template rendering."""
from __future__ import annotations

from pathlib import Path

TEMPLATES = Path(__file__).parent / "templates"


def render(template_name: str, subs: dict[str, str]) -> str:
    """Render a template file by substituting placeholder keys with values."""
    text = (TEMPLATES / template_name).read_text(encoding="utf-8")
    for key, value in subs.items():
        text = text.replace(key, value)
    return text
