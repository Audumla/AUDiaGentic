"""Document migration classification and reporting."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MigrationOutcome:
    source: str
    target: str | None
    result: str


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def classify_document(source: Path, target: Path | None) -> MigrationOutcome:
    source_text = _read_text(source)
    target_exists = target is not None and target.exists()
    target_text = _read_text(target) if target_exists and target is not None else ""
    target_identical = target_exists and target_text == source_text

    if "docs/releases" in source.as_posix():
        if target_exists and not target_identical:
            return MigrationOutcome(str(source), str(target), "skipped-conflict")
        return MigrationOutcome(str(source), str(target), "migrated")

    if "mixed" in source.as_posix():
        return MigrationOutcome(str(source), str(target) if target else None, "copied-for-review")

    return MigrationOutcome(str(source), str(target) if target else None, "skipped-ambiguous")


def migrate_documents(project_root: Path, sources: list[Path]) -> list[MigrationOutcome]:
    outcomes: list[MigrationOutcome] = []
    review_dir = project_root / ".audiagentic" / "runtime" / "migration" / "review"
    review_dir.mkdir(parents=True, exist_ok=True)

    for source in sources:
        relative = source.relative_to(project_root)
        target: Path | None = None
        if "docs/releases" in relative.as_posix():
            target = project_root / relative
        elif "mixed" in relative.as_posix():
            target = review_dir / source.name
        outcome = classify_document(source, target)
        if outcome.result == "copied-for-review" and target is not None:
            target.write_text(_read_text(source), encoding="utf-8")
        outcomes.append(outcome)
    return outcomes


def write_migration_report(project_root: Path, outcomes: list[MigrationOutcome]) -> Path:
    target_dir = project_root / ".audiagentic" / "runtime" / "migration"
    target_dir.mkdir(parents=True, exist_ok=True)
    report_path = target_dir / "report.json"
    report_payload = {
        "outcomes": [
            {"source": outcome.source, "target": outcome.target, "result": outcome.result}
            for outcome in outcomes
        ]
    }
    report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    return report_path
