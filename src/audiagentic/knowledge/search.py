from __future__ import annotations

import re
from collections import defaultdict

from .config import KnowledgeConfig
from .markdown_io import load_pages
from .models import SearchResult


def search_pages(config: KnowledgeConfig, query: str, limit: int = 10) -> list[SearchResult]:
    tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9_\-]+", query) if t.strip()]
    if not tokens:
        return []
    weights = config.search_weights
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
