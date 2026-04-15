from __future__ import annotations

from pathlib import Path

from .config import Config


def list_sections(
    kind: str, guidance_level: str = "standard", root: Path | None = None
) -> list[str]:
    """List sections for a document kind based on guidance level.

    Sections are loaded from config profiles, with fallback to defaults.
    """
    if root is None:
        root = Path(".")
    config = Config(root)
    template = config.document_template(kind, guidance_level)

    if not template:
        return []

    sections = []
    for line in template.split("\n"):
        if line.startswith("# "):
            section_name = line[2:].strip().lower().replace(" ", "_")
            if section_name and section_name not in sections:
                sections.append(section_name)

    return sections


def split_section_path(section_path: str) -> list[str]:
    """Split a section path into parts.

    Supports both dot notation (recommended: "section.subsection") and slash notation ("section/subsection").
    Normalizes to consistent part list regardless of delimiter used.
    """
    # Support both . and / as delimiters; normalize to dots
    path = section_path.replace("/", ".")
    return [part.strip() for part in path.split(".") if part.strip()]
