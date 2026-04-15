from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import yaml

from .models import KnowledgePage, Section

SECTION_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def iter_markdown_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    for path in sorted(root.rglob("*.md")):
        if path.is_file():
            yield path


def sidecar_for_page(pages_root: Path, meta_root: Path, page_path: Path) -> Path:
    relative = page_path.relative_to(pages_root)
    return meta_root / relative.with_suffix(".meta.yml")


def page_for_sidecar(meta_root: Path, pages_root: Path, meta_path: Path) -> Path:
    relative = meta_path.relative_to(meta_root)
    name = relative.name
    if not name.endswith(".meta.yml"):
        raise ValueError(f"Invalid sidecar suffix: {meta_path}")
    page_name = name[:-9] + ".md"
    return pages_root / relative.with_name(page_name)


def parse_markdown_sections(text: str) -> list[Section]:
    body = text.lstrip("\n")
    sections: list[Section] = []
    matches = list(SECTION_RE.finditer(body))
    if not matches:
        cleaned = body.strip()
        if cleaned:
            sections.append(Section(title="Body", body=cleaned))
        return sections
    for idx, section_match in enumerate(matches):
        title = section_match.group(2).strip()
        start = section_match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        section_body = body[start:end].strip("\n").strip()
        sections.append(Section(title=title, body=section_body))
    return sections


def render_markdown_sections(sections: list[Section]) -> str:
    parts: list[str] = []
    for section in sections:
        parts.append(f"## {section.title}")
        parts.append(section.body.rstrip())
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def load_page(content_path: Path, meta_path: Path) -> KnowledgePage:
    text = content_path.read_text(encoding="utf-8")
    metadata = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
    if not isinstance(metadata, dict):
        raise ValueError(f"Sidecar metadata must be a mapping in {meta_path}")
    return KnowledgePage(
        content_path=content_path,
        meta_path=meta_path,
        metadata=metadata,
        sections=parse_markdown_sections(text),
        raw_body=text,
    )


def save_page(page: KnowledgePage) -> None:
    page.content_path.parent.mkdir(parents=True, exist_ok=True)
    page.meta_path.parent.mkdir(parents=True, exist_ok=True)
    page.content_path.write_text(render_markdown_sections(page.sections), encoding="utf-8")
    page.meta_path.write_text(
        yaml.safe_dump(
            page.metadata, sort_keys=False, allow_unicode=True, width=100, default_flow_style=False
        ),
        encoding="utf-8",
    )


def load_pages(pages_root: Path, meta_root: Path) -> list[KnowledgePage]:
    pages: list[KnowledgePage] = []
    for content_path in iter_markdown_files(pages_root):
        meta_path = sidecar_for_page(pages_root, meta_root, content_path)
        if not meta_path.exists():
            continue
        pages.append(load_page(content_path, meta_path))
    return pages


def load_page_by_id(pages_root: Path, meta_root: Path, page_id: str) -> KnowledgePage | None:
    for page in load_pages(pages_root, meta_root):
        if page.page_id == page_id:
            return page
    return None


def iter_sidecars(meta_root: Path) -> Iterable[Path]:
    if not meta_root.exists():
        return
    for path in sorted(meta_root.rglob("*.meta.yml")):
        if path.is_file():
            yield path
