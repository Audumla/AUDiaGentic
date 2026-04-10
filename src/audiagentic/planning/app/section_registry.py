from __future__ import annotations

SECTION_KEYS = {
    "request": [],
    "spec": [
        "purpose",
        "scope",
        "requirements",
        "constraints",
        "acceptance_criteria",
    ],
    "plan": ["objectives", "delivery_approach", "dependencies"],
    "task": ["description", "acceptance_criteria", "notes", "implementation_notes"],
    "wp": [
        "objective",
        "scope_of_this_package",
        "inputs",
        "instructions",
        "required_outputs",
        "acceptance_checks",
        "non_goals",
    ],
    "reference": ["overview", "usage", "notes"],
}


def list_sections(kind: str) -> list[str]:
    return SECTION_KEYS.get(kind, [])


def split_section_path(section_path: str) -> list[str]:
    """Split a section path into parts.

    Supports both dot notation (recommended: "section.subsection") and slash notation ("section/subsection").
    Normalizes to consistent part list regardless of delimiter used.
    """
    # Support both . and / as delimiters; normalize to dots
    path = section_path.replace("/", ".")
    return [part.strip() for part in path.split(".") if part.strip()]

