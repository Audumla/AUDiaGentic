from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Section:
    title: str
    body: str


@dataclass(slots=True)
class KnowledgePage:
    content_path: Path
    meta_path: Path
    metadata: dict[str, Any]
    sections: list[Section]
    raw_body: str

    @property
    def page_id(self) -> str:
        return str(self.metadata.get("id", ""))

    @property
    def title(self) -> str:
        return str(self.metadata.get("title", self.content_path.stem))

    @property
    def page_type(self) -> str:
        return str(self.metadata.get("type", ""))

    @property
    def tags(self) -> list[str]:
        tags = self.metadata.get("tags", [])
        if isinstance(tags, str):
            return [t.strip() for t in tags.split(",") if t.strip()]
        if isinstance(tags, list):
            return [str(t) for t in tags]
        return []

    @property
    def section_map(self) -> dict[str, Section]:
        return {s.title: s for s in self.sections}


@dataclass(slots=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    path: str


@dataclass(slots=True)
class SearchResult:
    path: str
    page_id: str
    title: str
    score: float
    snippet: str
    matches: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PatchResult:
    changed: bool
    path: str
    actions_applied: list[str]
    message: str


@dataclass(slots=True)
class DriftItem:
    page_id: str
    title: str
    source_path: str
    status: str
    message: str
    fingerprint_before: str | None = None
    fingerprint_now: str | None = None
    diff_excerpt: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ImportResult:
    action: str
    page_id: str
    page_path: str
    meta_path: str
    source_path: str
    strategy: str
    message: str


@dataclass(slots=True)
class EventRecord:
    event_id: str
    adapter_id: str
    event_name: str
    source_path: str
    status: str
    observed_at: str
    affected_pages: list[str]
    fingerprint_before: str | None = None
    fingerprint_now: str | None = None
    summary: str | None = None
    diff_excerpt: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
