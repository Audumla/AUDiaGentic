from __future__ import annotations

from collections import Counter

from .config import KnowledgeConfig
from .markdown_io import (
    iter_markdown_files,
    iter_sidecars,
    load_page,
    load_pages,
    page_for_sidecar,
    sidecar_for_page,
)
from .models import ValidationIssue


def validate_vault(config: KnowledgeConfig) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    pages = load_pages(config.pages_root, config.meta_root)
    ids = [page.page_id for page in pages if page.page_id]
    duplicates = {page_id for page_id, count in Counter(ids).items() if count > 1}
    page_ids = {page.page_id for page in pages}
    archived_ids = _load_archive_ids(config)
    for content_path in iter_markdown_files(config.pages_root):
        meta_path = sidecar_for_page(config.pages_root, config.meta_root, content_path)
        if not meta_path.exists():
            issues.append(
                ValidationIssue(
                    "error",
                    "missing_sidecar",
                    "Page content has no sidecar metadata",
                    str(content_path.relative_to(config.root)),
                )
            )
    for meta_path in iter_sidecars(config.meta_root):
        content_path = page_for_sidecar(config.meta_root, config.pages_root, meta_path)
        if not content_path.exists():
            issues.append(
                ValidationIssue(
                    "error",
                    "orphan_sidecar",
                    "Sidecar metadata has no matching page content",
                    str(meta_path.relative_to(config.root)),
                )
            )
    for dup_id in duplicates:
        dup_pages = [p for p in pages if p.page_id == dup_id]
        paths = ", ".join(str(p.content_path.relative_to(config.root)) for p in dup_pages)
        issues.append(
            ValidationIssue("error", "duplicate_id", f"Duplicate id {dup_id}: {paths}", "")
        )
    for page in pages:
        path_str = str(page.content_path.relative_to(config.root))
        if not page.page_id:
            issues.append(
                ValidationIssue("error", "missing_id", "Page missing metadata.id", path_str)
            )
        for key in config.required_metadata:
            value = page.metadata.get(key)
            if value in (None, "", []):
                issues.append(
                    ValidationIssue(
                        "error",
                        "missing_metadata",
                        f"Required metadata '{key}' is missing",
                        path_str,
                    )
                )
        if config.allowed_types and page.page_type not in config.allowed_types:
            issues.append(
                ValidationIssue(
                    "error",
                    "invalid_type",
                    f"Page type '{page.page_type}' is not allowed",
                    path_str,
                )
            )
        section_names = {section.title for section in page.sections}
        for section_name in config.required_sections:
            if section_name not in section_names:
                issues.append(
                    ValidationIssue(
                        "error",
                        "missing_section",
                        f"Required section '{section_name}' is missing",
                        path_str,
                    )
                )
        related = page.metadata.get(config.related_field, []) or []
        if not isinstance(related, list):
            issues.append(
                ValidationIssue(
                    "error", "invalid_related", "Related field must be a list", path_str
                )
            )
        else:
            for rel in related:
                rel_id = str(rel)
                if rel_id in page_ids:
                    continue
                if config.allow_archived_links and rel_id in archived_ids:
                    continue
                issues.append(
                    ValidationIssue(
                        "warning",
                        "broken_related",
                        f"Related page '{rel_id}' was not found",
                        path_str,
                    )
                )
        source_refs = page.metadata.get("source_refs", []) or []
        if source_refs and not isinstance(source_refs, list):
            issues.append(
                ValidationIssue(
                    "error", "invalid_source_refs", "source_refs must be a list", path_str
                )
            )
    return issues


def _load_archive_ids(config: KnowledgeConfig) -> set[str]:
    """Load archived page IDs from the archive directory.

    Reads all markdown files in the archive directory and extracts their page IDs
    from sidecar metadata. Skips files that cannot be read or parsed.

    Args:
        config: Knowledge configuration with archive root path

    Returns:
        Set of archived page IDs

    Note:
        Silently skips files that raise OSError (file I/O errors) or ValueError
        (metadata parsing errors) to avoid failing validation on corrupted archives.
    """
    ids: set[str] = set()
    if not config.archive_root.exists():
        return ids
    for content_path in iter_markdown_files(config.archive_root):
        try:
            meta_path = sidecar_for_page(
                config.archive_root, config.archive_root / "_meta", content_path
            )
            if meta_path.exists():
                page = load_page(content_path, meta_path)
                if page.page_id:
                    ids.add(page.page_id)
        except OSError:
            continue
        except ValueError:
            continue
    return ids
