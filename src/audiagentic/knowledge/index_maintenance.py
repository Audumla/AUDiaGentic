from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import KnowledgeConfig
from .markdown_io import load_pages
from .models import KnowledgePage


def build_index_content(config: KnowledgeConfig, pages: list[KnowledgePage]) -> str:
    """Build index page content from loaded pages.

    Organizes pages by type and generates a structured index with links.

    Args:
        config: Knowledge configuration
        pages: List of knowledge pages to index

    Returns:
        Markdown content for the index page
    """
    lines = ["# Knowledge Index", "", "This vault stores current-state project knowledge.", ""]

    # Group pages by type
    by_type: dict[str, list[KnowledgePage]] = {}
    for page in pages:
        page_type = page.page_type or "unknown"
        by_type.setdefault(page_type, []).append(page)

    # Sort types and pages within each type
    for page_type in sorted(by_type.keys()):
        type_pages = sorted(by_type[page_type], key=lambda p: p.title.lower())
        lines.append(f"## {page_type.replace('_', ' ').title()}")
        lines.append("")
        for page in type_pages:
            link = f"[{page.title}]({page.page_id})"
            tags = page.metadata.get("tags", []) or []
            if tags:
                tag_str = ", ".join(str(t) for t in tags[:3])
                link += f" (`{tag_str}`)"
            lines.append(f"- {link}")
        lines.append("")

    return "\n".join(lines)


def maintain_index_pages(config: KnowledgeConfig) -> list[Path]:
    """Maintain index pages across the knowledge vault.

    Ensures that:
    1. Root index page (docs/knowledge/index.md) is up to date
    2. Type-specific index pages exist and are current
    3. Cross-references between pages are valid

    Args:
        config: Knowledge configuration

    Returns:
        List of index pages that were created or updated
    """
    updated: list[Path] = []

    # Load all pages
    pages = load_pages(config.pages_root, config.meta_root)

    # Update root index
    root_index = config.root / "docs" / "knowledge" / "index.md"
    root_index.parent.mkdir(parents=True, exist_ok=True)

    new_content = build_index_content(config, pages)
    current_content = root_index.read_text(encoding="utf-8") if root_index.exists() else ""

    if current_content.strip() != new_content.strip():
        root_index.write_text(new_content, encoding="utf-8")
        updated.append(root_index)

    # Update type-specific indexes
    by_type: dict[str, list[KnowledgePage]] = {}
    for page in pages:
        page_type = page.page_type or "unknown"
        by_type.setdefault(page_type, []).append(page)

    for page_type, type_pages in by_type.items():
        type_dir = config.pages_root / page_type
        type_index = type_dir / "index.md"

        # Build type-specific index content
        type_lines = [f"# {page_type.replace('_', ' ').title()} Pages", ""]
        type_lines.append(f"Pages of type `{page_type}`:\n")
        for page in sorted(type_pages, key=lambda p: p.title.lower()):
            if page.page_id != f"{page_type}/index":
                type_lines.append(f"- [{page.title}]({page.page_id})")
        type_lines.append("")

        type_content = "\n".join(type_lines)
        current_type_content = type_index.read_text(encoding="utf-8") if type_index.exists() else ""

        if current_type_content.strip() != type_content.strip():
            type_index.parent.mkdir(parents=True, exist_ok=True)
            type_index.write_text(type_content, encoding="utf-8")
            updated.append(type_index)

    return updated


def validate_index_links(config: KnowledgeConfig) -> list[dict[str, Any]]:
    """Validate that all links in index pages point to existing pages.

    Args:
        config: Knowledge configuration

    Returns:
        List of validation errors (empty if all links are valid)
    """
    errors: list[dict[str, Any]] = []

    # Load all pages to get valid page IDs
    pages = load_pages(config.pages_root, config.meta_root)
    valid_ids = {p.page_id for p in pages}

    # Check root index
    root_index = config.root / "docs" / "knowledge" / "index.md"
    if root_index.exists():
        errors.extend(_validate_links_in_file(root_index, valid_ids))

    # Check type-specific indexes
    for type_dir in config.pages_root.iterdir():
        if type_dir.is_dir():
            type_index = type_dir / "index.md"
            if type_index.exists():
                errors.extend(_validate_links_in_file(type_index, valid_ids))

    return errors


def _validate_links_in_file(file_path: Path, valid_ids: set[str]) -> list[dict[str, Any]]:
    """Validate links in a single file.

    Args:
        file_path: Path to the file to check
        valid_ids: Set of valid page IDs

    Returns:
        List of validation errors
    """
    errors: list[dict[str, Any]] = []
    content = file_path.read_text(encoding="utf-8")

    # Find markdown links [title](page_id)
    import re

    link_pattern = re.compile(r"\[([^\]]+)\]\(([^\)]+)\)")
    for match in link_pattern.finditer(content):
        link_target = match.group(2)
        # Skip external URLs
        if link_target.startswith("http://") or link_target.startswith("https://"):
            continue
        # Skip anchor links
        if link_target.startswith("#"):
            continue
        # Check if it's a valid page ID
        if link_target not in valid_ids:
            errors.append(
                {
                    "file": str(file_path.relative_to(config.root)),
                    "link": link_target,
                    "error": "broken_link",
                    "message": f"Link to non-existent page: {link_target}",
                }
            )

    return errors


def refresh_index(config: KnowledgeConfig) -> dict[str, Any]:
    """Refresh all index pages and validate links.

    This is the main entry point for index maintenance.

    Args:
        config: Knowledge configuration

    Returns:
        Result dict with updated files and validation status
    """
    updated = maintain_index_pages(config)
    errors = validate_index_links(config)

    return {
        "updated_files": [str(p.relative_to(config.root)) for p in updated],
        "validation_errors": errors,
        "status": "valid" if not errors else "invalid",
    }
