from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.runtime.release.history_import import import_legacy_history
from tests.helpers import sandbox as sandbox_helper

FIXTURES = ROOT / "docs" / "examples" / "fixtures"


def test_history_import_deterministic(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "history-import")
    try:
        changelog = sandbox.repo / "docs" / "releases" / "CHANGELOG.md"
        changelog.parent.mkdir(parents=True)
        changelog.write_text((FIXTURES / "legacy-changelog.sample.md").read_text(encoding="utf-8"), encoding="utf-8")

        events = import_legacy_history(sandbox.repo, changelog)
        assert len(events) == 2
        assert events[0]["event-id"] == "chg_legacy_0001"
        report = sandbox.repo / ".audiagentic" / "runtime" / "ledger" / "import" / "report.json"
        assert report.is_file()
    finally:
        sandbox.cleanup()


def test_history_import_missing_file(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "history-import-missing")
    try:
        missing = sandbox.repo / "docs" / "releases" / "MISSING.md"
        try:
            import_legacy_history(sandbox.repo, missing)
        except AudiaGenticError as exc:
            assert exc.kind == "validation"
            report = sandbox.repo / ".audiagentic" / "runtime" / "ledger" / "import" / "report.json"
            assert not report.exists()
        else:
            raise AssertionError("expected validation error")
    finally:
        sandbox.cleanup()
