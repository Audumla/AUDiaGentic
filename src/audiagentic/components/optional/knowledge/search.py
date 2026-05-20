from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

try:
    from rapidfuzz import fuzz as _fuzz

    _FUZZY_AVAILABLE = True
except ImportError:
    _FUZZY_AVAILABLE = False

from .config import KnowledgeConfig
from .markdown_io import load_pages
from .models import SearchResult


def filter_by_metadata(pages: list, filters: dict[str, Any]) -> list:
    """Filter pages by metadata fields.

    Supports:
    - type: page type (single value or list)
    - tags: tags (single value or list, matches if any tag matches)
    - owners: owners (single value or list, matches if any owner matches)
    - id: page_id (single value or list)
    - title: title contains (single value)

    Args:
        pages: List of KnowledgePage objects
        filters: Dict with filter keys and values

    Returns:
        Filtered list of pages
    """
    if not filters:
        return pages

    filtered = pages

    # Filter by type
    if "type" in filters:
        type_values = filters["type"]
        if isinstance(type_values, str):
            type_values = [type_values]
        filtered = [p for p in filtered if p.page_type.lower() in [t.lower() for t in type_values]]

    # Filter by tags (OR logic within tags, AND with other filters)
    if "tags" in filters:
        tag_values = filters["tags"]
        if isinstance(tag_values, str):
            tag_values = [tag_values]
        tag_values_lower = [t.lower() for t in tag_values]
        filtered = [p for p in filtered if any(tag.lower() in tag_values_lower for tag in p.tags)]

    # Filter by owners (OR logic within owners, AND with other filters)
    if "owners" in filters:
        owner_values = filters["owners"]
        if isinstance(owner_values, str):
            owner_values = [owner_values]
        owner_values_lower = [o.lower() for o in owner_values]
        filtered = [
            p
            for p in filtered
            if any(
                owner.lower() in owner_values_lower
                for owner in (
                    p.metadata.get("owners", [])
                    if isinstance(p.metadata.get("owners"), list)
                    else [o.strip() for o in p.metadata.get("owners", "").split(",") if o.strip()]
                )
            )
        ]

    # Filter by id
    if "id" in filters:
        id_values = filters["id"]
        if isinstance(id_values, str):
            id_values = [id_values]
        filtered = [p for p in filtered if p.page_id in id_values]

    # Filter by title (contains)
    if "title" in filters:
        title_query = filters["title"].lower()
        filtered = [p for p in filtered if title_query in p.title.lower()]

    return filtered


def search_pages(config: KnowledgeConfig, query: str, limit: int = 10) -> list[SearchResult]:
    """Search pages using token matching with optional fuzzy boost.

    Exact token matches are scored by field weight. When rapidfuzz is available
    and a query has no exact matches for a page, fuzzy scoring provides a boost
    if the ratio exceeds config.search_fuzzy_threshold.
    """
    tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9_\-]+", query) if t.strip()]
    if not tokens:
        return []

    weights = config.search_weights
    fuzzy_threshold = config.search_fuzzy_threshold
    fuzzy_weight = config.search_fuzzy_weight
    token_patterns = [
        re.compile(r"\b" + re.escape(token) + r"\b", re.IGNORECASE) for token in tokens
    ]
    results: list[SearchResult] = []

    for page in load_pages(config.pages_root, config.meta_root):
        score = 0.0
        matches: dict[str, int] = defaultdict(int)
        title = page.title.lower()
        tag_blob = " ".join(page.tags).lower()
        section_blob = " ".join(section.title for section in page.sections).lower()
        body_blob = " ".join(section.body for section in page.sections).lower()

        for token, pattern in zip(tokens, token_patterns):
            if pattern.search(title):
                score += weights["title"]
                matches["title"] += 1
            if pattern.search(tag_blob):
                score += weights["tags"]
                matches["tags"] += 1
            if pattern.search(section_blob):
                score += weights["sections"]
                matches["sections"] += 1
            body_count = len(pattern.findall(body_blob))
            if body_count:
                score += weights["body"] * body_count
                matches["body"] += body_count

        # Fuzzy boost: when exact scoring is zero, try fuzzy on title + body
        if score == 0.0 and _FUZZY_AVAILABLE:
            query_lower = query.lower()
            title_ratio = _fuzz.partial_ratio(query_lower, title)
            body_ratio = _fuzz.partial_ratio(query_lower, body_blob[:500])  # limit body for perf
            best_ratio = max(title_ratio, body_ratio)
            if best_ratio >= fuzzy_threshold:
                score = (best_ratio / 100.0) * fuzzy_weight
                matches["fuzzy"] += 1

        if score <= 0:
            continue

        snippet = _build_snippet(body_blob, tokens, config.snippet_length)
        results.append(
            SearchResult(
                path=str(page.content_path.relative_to(config.root)),
                page_id=page.page_id,
                title=page.title,
                score=score,
                snippet=snippet,
                matches=[f"{k}:{v}" for k, v in sorted(matches.items())],
            )
        )

    results.sort(key=lambda item: (-item.score, item.title.lower()))
    return results[:limit]


def _build_snippet(text: str, tokens: list[str], width: int) -> str:
    position = min((text.find(token) for token in tokens if text.find(token) >= 0), default=0)
    start = max(0, position - width // 3)
    end = min(len(text), start + width)
    snippet = text[start:end].strip()
    return snippet if len(snippet) < len(text) else snippet + "..."
