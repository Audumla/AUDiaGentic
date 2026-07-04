"""Generic frontmatter handling for markdown documents.

Module-level functions parse and render ``---`` YAML frontmatter and
``## Heading`` sections of markdown documents; the FrontmatterBuilder class
assembles frontmatter dicts from config defaults and provided values.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from .interfaces import WorkflowConfig

_TITLE_RE = re.compile(r"^# (.+)$", re.MULTILINE)
_SECTION_RE = re.compile(r"^## (.+)$", re.MULTILINE)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a markdown document into (frontmatter dict, body).

    Returns ``({}, text)`` unchanged when no ``---`` frontmatter block leads
    the document.
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm: dict[str, Any] = yaml.safe_load(text[3:end].strip()) or {}
    body = text[end + 4:].lstrip("\n")
    return fm, body


def render_frontmatter(fm: dict[str, Any], body: str) -> str:
    """Render a frontmatter dict and body back into a markdown document."""
    fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False).rstrip()
    return f"---\n{fm_str}\n---\n\n{body}"


def parse_title(body: str) -> str | None:
    """Return the first ``# Title`` heading of a markdown body, if present."""
    match = _TITLE_RE.match(body)
    return match.group(1).strip() if match else None


def parse_sections(body: str, heading_to_field: dict[str, str]) -> dict[str, str]:
    """Extract ``## Heading`` sections into a field->content dict.

    ``heading_to_field`` maps document headings to result keys; unknown
    headings are skipped. The ``# Title`` heading, when present, is returned
    under ``title``.
    """
    result: dict[str, str] = {}
    title = parse_title(body)
    if title is not None:
        result["title"] = title
    headings = list(_SECTION_RE.finditer(body))
    for i, match in enumerate(headings):
        field = heading_to_field.get(match.group(1).strip())
        if field is None:
            continue
        start = match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        result[field] = body[start:end].strip()
    return result


def build_sectioned_body(title: str, sections: dict[str, str], field_to_heading: dict[str, str]) -> str:
    """Render a title plus ordered ``## Heading`` sections into a markdown body."""
    parts = [f"# {title}"]
    for key, heading in field_to_heading.items():
        content = sections.get(key, "")
        parts.append(f"\n## {heading}\n\n{content}")
    return "\n".join(parts) + "\n"


class FrontmatterBuilder:
    def __init__(self, config: WorkflowConfig):
        self.config = config

    def build(
        self,
        *,
        kind: str,
        id_: str,
        label: str,
        summary: str,
        domain: str | None,
        workflow: str | None,
        refs: dict[str, object] | None,
        fields: dict[str, object] | None,
        profile: str | None,
        guidance: str | None,
        current_understanding: str | None,
        open_questions: list[str] | None,
        source: str | None,
        context: str | None,
        state: str | None = None,
    ) -> dict:
        if guidance is None:
            guidance = self.config.default_guidance()

        frontmatter = {
            "id": id_,
            "label": label,
            "state": state or self.config.initial_state(kind, workflow),
            "summary": summary,
        }

        if domain:
            frontmatter["domain"] = domain

        input_values = dict(refs or {})
        seed_field_sources = self.config.seeded_reference_fields(kind)

        for field in self.config.reference_fields(kind):
            if field in input_values:
                value = input_values.get(field)
            elif field in seed_field_sources:
                value = input_values.get(seed_field_sources[field])
            elif self.config.reference_field_shape(field) == "rel_list":
                value = []
            else:
                value = None
            value = self._coerce_reference_value(field, value)

            if value in (None, [], ""):
                continue
            frontmatter[field] = value

        if workflow:
            frontmatter["workflow"] = workflow

        frontmatter.update(
            self.config.build_creation_extra_fields(
                kind,
                summary=summary,
                guidance=guidance,
                profile=profile,
                current_understanding=current_understanding,
                open_questions=open_questions,
                source=source,
                context=context,
            )
        )
        for field, value in (fields or {}).items():
            if value not in (None, [], ""):
                frontmatter[field] = value

        return frontmatter

    def _coerce_reference_value(self, field: str, value):
        if value is None:
            return None
        shape = self.config.reference_field_shape(field)
        if shape == "scalar_ref_list" and isinstance(value, str):
            return [value]
        if shape == "scalar_ref" and isinstance(value, list):
            return value[0] if len(value) == 1 else None
        if shape == "rel_list":
            if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
                return [{"ref": v, "seq": (i + 1) * 1000} for i, v in enumerate(value)]
        return value
