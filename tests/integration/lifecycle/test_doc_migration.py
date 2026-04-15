from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from tests.helpers import sandbox as sandbox_helper

from audiagentic.runtime.lifecycle.migration import migrate_documents, write_migration_report


def test_doc_migration_report_deterministic(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "doc-migration")
    try:
        release_dir = sandbox.repo / "docs" / "releases"
        release_dir.mkdir(parents=True)
        (release_dir / "CHANGELOG.md").write_text("legacy", encoding="utf-8")

        mixed_dir = sandbox.repo / "docs" / "mixed_notes"
        mixed_dir.mkdir(parents=True)
        (mixed_dir / "release_and_design.md").write_text("mixed", encoding="utf-8")

        notes_dir = sandbox.repo / "notes"
        notes_dir.mkdir(parents=True)
        (notes_dir / "tmp.md").write_text("tmp", encoding="utf-8")

        sources = [
            release_dir / "CHANGELOG.md",
            mixed_dir / "release_and_design.md",
            notes_dir / "tmp.md",
        ]
        outcomes = migrate_documents(sandbox.repo, sources)
        report = write_migration_report(sandbox.repo, outcomes)
        payload = json.loads(report.read_text(encoding="utf-8"))
        results = {entry["source"]: entry["result"] for entry in payload["outcomes"]}
        assert results[str(release_dir / "CHANGELOG.md")] == "migrated"
        assert results[str(mixed_dir / "release_and_design.md")] == "copied-for-review"
        assert results[str(notes_dir / "tmp.md")] == "skipped-ambiguous"
        review_copy = sandbox.repo / ".audiagentic" / "runtime" / "migration" / "review" / "release_and_design.md"
        assert review_copy.is_file()
    finally:
        sandbox.cleanup()


def test_doc_migration_failure_does_not_write_report(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "doc-migration-failure")
    try:
        missing = sandbox.repo / "docs" / "missing.md"
        try:
            migrate_documents(sandbox.repo, [missing])
        except FileNotFoundError:
            report = sandbox.repo / ".audiagentic" / "runtime" / "migration" / "report.json"
            assert not report.exists()
        else:
            raise AssertionError("expected FileNotFoundError")
    finally:
        sandbox.cleanup()
