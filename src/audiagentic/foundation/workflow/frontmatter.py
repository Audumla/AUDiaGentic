"""Generic frontmatter handling for markdown documents.

Module-level functions parse and render ``---`` YAML frontmatter and
``## Heading`` sections of markdown documents; the FrontmatterBuilder class
assembles frontmatter dicts from config defaults and provided values.
"""

from __future__ import annotations

import re
from typing import Any

import yaml
from markdown_it import MarkdownIt

from .interfaces import WorkflowConfig

_TITLE_RE = re.compile(r"^# (.+)$", re.MULTILINE)
_MD = MarkdownIt()


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
    body = text[end + 4 :].lstrip("\n")
    return fm, body


def render_frontmatter(fm: dict[str, Any], body: str) -> str:
    """Render a frontmatter dict and body back into a markdown document."""
    fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False).rstrip()
    return f"---\n{fm_str}\n---\n\n{body}"


def parse_title(body: str) -> str | None:
    """Return the first ``# Title`` heading of a markdown body, if present."""
    match = _TITLE_RE.match(body)
    return match.group(1).strip() if match else None


def _slugify_heading(heading: str) -> str:
    """Convert a heading to a stable lowercase dict key.

    Replaces non-alphanumeric characters with underscores so keys are
    consistent across round-trips regardless of original capitalization.
    """
    return re.sub(r"[^a-z0-9]+", "_", heading.strip().lower()).strip("_")


def _reconstruct_heading(key: str, first: bool = True) -> str:
    """Reconstruct a readable heading from a slugified key.

    Capitalizes the first word and words longer than 3 characters,
    leaves short words (and/or/for/etc.) lowercase.
    """
    parts = key.replace("_", " ").split()
    return " ".join(word.capitalize() if (first or len(word) > 3) else word for word in parts)


def _heading_level(token: Any) -> int:
    """Extract the numeric heading level from a markdown-it heading_open token.

    Returns 1 for 'h1', 2 for 'h2', etc. Returns 0 if parsing fails.
    """
    tag = getattr(token, "tag", "") or ""
    try:
        return int(tag[1])
    except (IndexError, ValueError):
        return 0


def _extract_heading_text(tokens: list, token_idx: int) -> str:
    """Extract the text content from the inline token following a heading_open."""
    for next_token in tokens[token_idx + 1 :]:
        if next_token.type == "inline":
            return "".join(
                child.content for child in (next_token.children or []) if child.type == "text"
            ).strip()
        break
    return ""


def _lines(body: str) -> list[str]:
    """Return body split into lines, preserving \n as the separator."""
    return body.split("\n")


def _section_content(lines: list[str], start_line: int, end_line: int | None) -> str:
    """Extract section content between line numbers (0-based, inclusive start, exclusive end)."""
    if end_line is None:
        return "\n".join(lines[start_line:]).strip()
    return "\n".join(lines[start_line:end_line]).strip()


def parse_sections(body: str, heading_to_field: dict[str, str]) -> dict[str, str]:
    """Extract ``## Heading`` sections into a field->content dict.

    Uses a proper markdown parser (markdown-it-py) so that:
    - heading hierarchy is respected (h3+ content stays embedded in parent)
    - headings inside code blocks are ignored
    - nested sub-headings are preserved as text, not promoted to new fields

    ``heading_to_field`` maps document headings to result keys; unknown
    headings are included using their slugified heading text as the key.
    The ``# Title`` heading, when present, is returned under ``title``.

    Slugifying is lossy — capitalization and punctuation cannot be recovered
    from the key. Pair this with :func:`parse_custom_headings` and pass the
    result to :func:`build_sectioned_body` so a round-trip preserves the
    author's original heading text.
    """
    result: dict[str, str] = {}
    title = parse_title(body)
    if title is not None:
        result["title"] = title

    tokens = _MD.parse(body)
    body_lines = _lines(body)

    # Collect h2 headings as section boundaries (h3+ stays embedded in parent).
    # Each entry: (heading_text, start_line)
    heading_entries: list[tuple[str, int]] = []
    for i, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        level = _heading_level(token)
        if level != 2:
            continue
        heading_text = _extract_heading_text(tokens, i)
        map_start = token.map[0] if token.map else 0
        heading_entries.append((heading_text, map_start))

    # Compute content boundaries: each section runs from after its heading
    # to the start of the next h2+ heading (or end of body).
    for idx, (heading_text, map_start) in enumerate(heading_entries):
        field = heading_to_field.get(heading_text)
        if field is None:
            field = _slugify_heading(heading_text)

        # Content starts on the line after this heading.
        content_start = map_start + 1

        # Find where this section ends: next h2+ heading or end of body.
        if idx + 1 < len(heading_entries):
            next_map_start = heading_entries[idx + 1][1]
            result[field] = _section_content(body_lines, content_start, next_map_start)
        else:
            result[field] = _section_content(body_lines, content_start, None)

    return result


def parse_custom_headings(body: str, heading_to_field: dict[str, str]) -> dict[str, str]:
    """Return ``slug -> original heading text`` for headings not in the map.

    Only custom headings are returned; known sections already have canonical
    spellings in ``heading_to_field`` and must not be overridden by whatever
    the file happened to contain.
    """
    result: dict[str, str] = {}
    tokens = _MD.parse(body)
    for token in tokens:
        if token.type != "heading_open":
            continue
        # Only consider h2+ headings (same as parse_sections).
        level = _heading_level(token)
        if level != 2:
            continue
        heading_text = _extract_heading_text(tokens, tokens.index(token))
        if heading_text in heading_to_field:
            continue
        result[_slugify_heading(heading_text)] = heading_text
    return result


def build_sectioned_body(
    title: str,
    sections: dict[str, str],
    field_to_heading: dict[str, str],
    custom_headings: dict[str, str] | None = None,
) -> str:
    """Render a title plus ordered ``## Heading`` sections into a markdown body.

    Known sections are written using their canonical heading from
    ``field_to_heading``; unknown (custom) sections are appended after.

    ``custom_headings`` maps a custom section's slug to the heading text it
    was read with, so an existing heading survives a round-trip verbatim.
    A slug with no entry — a section being created for the first time — falls
    back to a reconstructed heading, which is the only case where the lossy
    reconstruction is correct, because there is no original to preserve.
    """
    custom_headings = custom_headings or {}
    parts = [f"# {title}"]
    for key, heading in field_to_heading.items():
        content = sections.get(key, "")
        parts.append(f"\n## {heading}\n\n{content}")
    # Append any unknown sections not in the heading map
    for key, content in sections.items():
        if key == "title" or key in field_to_heading:
            continue
        heading = custom_headings.get(key) or _reconstruct_heading(key)
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
