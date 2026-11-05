"""A branch that still appended to the frozen baseline is converted to per-event files."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from audiagentic.components.ledger import ledger_api
from audiagentic.components.ledger.current_events import event_path, iter_events
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


def _event(event_id: str, **extra) -> dict:
    return {"event-id": event_id, "timestamp-utc": "2026-11-01T00:00:00Z", "change-class": "feature",
            "files": ["src/a.py"], "technical-summary": "t", "user-summary-candidate": "u",
            "status": "unreleased", **extra}


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _repo_with_baseline(tmp_path: Path, rows: list[dict]) -> Path:
    baseline = tmp_path / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    baseline.parent.mkdir(parents=True)
    baseline.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return baseline


def test_rows_appended_since_the_base_become_event_files_and_the_baseline_is_restored(tmp_path: Path) -> None:
    baseline = _repo_with_baseline(tmp_path, [_event("chg_old")])
    original = baseline.read_text()
    with baseline.open("a") as handle:  # what an older ledger tool did on a branch
        handle.write(json.dumps(_event("chg_new_1"), sort_keys=True) + "\n")
        handle.write(json.dumps(_event("chg_new_2"), sort_keys=True) + "\n")

    result = ledger_api.convert_legacy_baseline(tmp_path, "HEAD")

    assert result == {"converted": ["chg_new_1", "chg_new_2"], "rejected": [], "already-present": [], "restored": True}
    assert baseline.read_text() == original  # byte-identical to the base: no ledger conflict is left to merge
    assert event_path(tmp_path, "chg_new_1").is_file() and event_path(tmp_path, "chg_new_2").is_file()
    assert [e["event-id"] for e in iter_events(tmp_path)] == ["chg_old", "chg_new_1", "chg_new_2"]
    assert ledger_api.convert_legacy_baseline(tmp_path, "HEAD")["converted"] == []  # idempotent


def test_a_row_the_contract_rejects_is_reported_and_the_baseline_is_left_alone(tmp_path: Path) -> None:
    baseline = _repo_with_baseline(tmp_path, [_event("chg_old")])
    with baseline.open("a") as handle:
        handle.write(json.dumps(_event("chg_bad", **{"change-class": "perf"})) + "\n")
        handle.write(json.dumps(_event("chg_ok")) + "\n")
    appended = baseline.read_text()

    result = ledger_api.convert_legacy_baseline(tmp_path, "HEAD")

    assert result["converted"] == [] and [r["event-id"] for r in result["rejected"]] == ["chg_bad"]
    assert result["restored"] is False and baseline.read_text() == appended  # nothing is dropped silently
    assert not event_path(tmp_path, "chg_ok").exists()  # all-or-nothing: the good row waits for the bad one


def test_a_missing_base_ref_fails_closed(tmp_path: Path) -> None:
    import pytest

    from audiagentic.foundation.contracts.errors import AudiaGenticError

    _repo_with_baseline(tmp_path, [_event("chg_old")])
    with pytest.raises(AudiaGenticError):
        ledger_api.convert_legacy_baseline(tmp_path, "no-such-ref")


def test_a_baseline_that_lost_or_changed_a_base_row_is_refused_untouched(tmp_path: Path) -> None:
    baseline = _repo_with_baseline(tmp_path, [_event("chg_old"), _event("chg_old2")])
    for broken in (
        json.dumps(_event("chg_old")) + "\n",  # a base row was deleted
        json.dumps(_event("chg_old")) + "\n" + json.dumps(_event("chg_old2", **{"technical-summary": "x"})) + "\n",  # edited
    ):
        baseline.write_text(broken)
        with pytest.raises(AudiaGenticError, match="lost, changed or reordered"):
            ledger_api.convert_legacy_baseline(tmp_path, "HEAD")
        assert baseline.read_text() == broken


def test_merge_markers_left_by_a_conflicted_merge_are_refused(tmp_path: Path) -> None:
    baseline = _repo_with_baseline(tmp_path, [_event("chg_old")])
    baseline.write_text(baseline.read_text() + "<<<<<<< HEAD\n" + json.dumps(_event("chg_x")) + "\n>>>>>>> other\n")
    result = ledger_api.convert_legacy_baseline(tmp_path, "HEAD")
    assert result["converted"] == [] and result["restored"] is False and len(result["rejected"]) == 2
    assert not list((tmp_path / "docs" / "releases" / "events").glob("*.json"))  # nothing is written on rejection


def test_one_bad_row_writes_nothing_and_a_row_conflicting_with_the_baseline_is_rejected(tmp_path: Path) -> None:
    baseline = _repo_with_baseline(tmp_path, [_event("chg_old")])
    with baseline.open("a") as handle:
        handle.write(json.dumps(_event("chg_good")) + "\n")
        handle.write(json.dumps(_event("chg_old", **{"technical-summary": "different"})) + "\n")
    result = ledger_api.convert_legacy_baseline(tmp_path, "HEAD")
    assert [r["event-id"] for r in result["rejected"]] == ["chg_old"] and result["converted"] == []
    assert not event_path(tmp_path, "chg_good").exists()  # all-or-nothing: no half-converted tree


def test_a_row_conflicting_with_a_released_event_is_rejected(tmp_path: Path) -> None:
    baseline = _repo_with_baseline(tmp_path, [_event("chg_old")])
    historical = tmp_path / "docs" / "releases" / "LEDGER.ndjson"
    historical.write_text(json.dumps({**_event("chg_rel"), "status": "released", "release-id": "r1"}) + "\n")
    with baseline.open("a") as handle:
        handle.write(json.dumps(_event("chg_rel", **{"technical-summary": "different"})) + "\n")
    assert ledger_api.convert_legacy_baseline(tmp_path, "HEAD")["rejected"][0]["event-id"] == "chg_rel"


def test_a_baseline_absent_at_the_merge_base_is_restored_to_absence(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("x\n")
    _git(tmp_path, "init", "-q", "-b", "main")
    _commit_all(tmp_path, "base")
    baseline = tmp_path / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(json.dumps(_event("chg_new")) + "\n")

    result = ledger_api.convert_legacy_baseline(tmp_path, "HEAD")

    assert result["converted"] == ["chg_new"] and result["restored"] is True
    assert not baseline.exists()  # the base never had one: its absence is restored, not an empty file


def test_the_branch_baseline_is_compared_with_the_merge_base_not_the_moved_main(tmp_path: Path) -> None:
    baseline = _repo_with_baseline(tmp_path, [_event("chg_old")])
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    with baseline.open("a") as handle:
        handle.write(json.dumps(_event("chg_branch")) + "\n")
    _commit_all(tmp_path, "branch row")
    _git(tmp_path, "checkout", "-q", "main")
    with baseline.open("a") as handle:  # main moved on (another PR appended before the freeze)
        handle.write(json.dumps(_event("chg_main")) + "\n")
    _commit_all(tmp_path, "main row")
    _git(tmp_path, "checkout", "-q", "feature")

    result = ledger_api.convert_legacy_baseline(tmp_path, "main")

    assert result["converted"] == ["chg_branch"] and result["restored"] is True
    assert [json.loads(line)["event-id"] for line in baseline.read_text().splitlines()] == ["chg_old"]
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "convert")
    _git(tmp_path, "merge", "-q", "--no-edit", "main")  # no conflict: the branch no longer touches the baseline
    assert [e["event-id"] for e in iter_events(tmp_path)] == ["chg_old", "chg_main", "chg_branch"]


def test_a_branch_that_merged_main_with_a_union_resolution_converts_cleanly(tmp_path: Path) -> None:
    """The common shape: the branch's rows ended up interleaved before main's after a union-merge resolution."""
    baseline = _repo_with_baseline(tmp_path, [_event("chg_base")])
    (tmp_path / ".gitattributes").write_text("docs/releases/CURRENT_RELEASE_LEDGER.ndjson merge=union\n")
    _commit_all(tmp_path, "attributes")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    with baseline.open("a") as handle:
        handle.write(json.dumps(_event("chg_branch_1")) + "\n")
    _commit_all(tmp_path, "branch 1")
    _git(tmp_path, "checkout", "-q", "main")
    with baseline.open("a") as handle:
        handle.write(json.dumps(_event("chg_main_1")) + "\n")
    _commit_all(tmp_path, "main 1")
    _git(tmp_path, "checkout", "-q", "feature")
    _git(tmp_path, "merge", "-q", "--no-edit", "main")  # union keeps both sides: branch row before main row
    with baseline.open("a") as handle:
        handle.write(json.dumps(_event("chg_branch_2")) + "\n")
    _commit_all(tmp_path, "branch 2")
    assert [json.loads(line)["event-id"] for line in baseline.read_text().splitlines()] == [
        "chg_base", "chg_branch_1", "chg_main_1", "chg_branch_2"]

    result = ledger_api.convert_legacy_baseline(tmp_path, "main")

    assert result == {"converted": ["chg_branch_1", "chg_branch_2"], "rejected": [], "already-present": [],
                      "restored": True}
    assert [json.loads(line)["event-id"] for line in baseline.read_text().splitlines()] == ["chg_base", "chg_main_1"]
    assert [e["event-id"] for e in iter_events(tmp_path)] == ["chg_base", "chg_main_1", "chg_branch_1", "chg_branch_2"]
    assert ledger_api.convert_legacy_baseline(tmp_path, "main")["converted"] == []  # a second run finds nothing to do


def test_reordered_base_rows_are_refused_even_though_every_row_is_present(tmp_path: Path) -> None:
    baseline = _repo_with_baseline(tmp_path, [_event("chg_a"), _event("chg_b"), _event("chg_c")])
    rows = [json.dumps(_event(i)) for i in ("chg_c", "chg_a", "chg_x", "chg_b")]
    baseline.write_text("\n".join(rows) + "\n")
    with pytest.raises(AudiaGenticError, match="reordered"):
        ledger_api.convert_legacy_baseline(tmp_path, "HEAD")
    assert not event_path(tmp_path, "chg_x").exists()


def test_an_identical_copy_of_a_base_row_is_reported_not_silently_dropped(tmp_path: Path) -> None:
    baseline = _repo_with_baseline(tmp_path, [_event("chg_old")])
    with baseline.open("a") as handle:
        handle.write(json.dumps(_event("chg_old"), sort_keys=True) + "\n")  # a duplicate of the base row
        handle.write(json.dumps(_event("chg_new")) + "\n")
    result = ledger_api.convert_legacy_baseline(tmp_path, "HEAD")
    assert result["converted"] == ["chg_new"] and result["already-present"] == ["chg_old"] and result["restored"] is True


def test_duplicate_rejected_rows_report_their_own_line_numbers(tmp_path: Path) -> None:
    baseline = _repo_with_baseline(tmp_path, [_event("chg_old")])
    bad = json.dumps(_event("chg_bad", **{"change-class": "perf"}))
    with baseline.open("a") as handle:
        handle.write(bad + "\n" + json.dumps(_event("chg_mid")) + "\n" + bad + "\n")
    result = ledger_api.convert_legacy_baseline(tmp_path, "HEAD")
    assert [r["line"] for r in result["rejected"]] == ["2", "4"]


def test_a_failure_while_writing_leaves_only_verified_event_files_and_a_rerun_converges(tmp_path: Path, monkeypatch) -> None:
    from audiagentic.components.ledger import conversion

    baseline = _repo_with_baseline(tmp_path, [_event("chg_old")])
    original = baseline.read_text()
    with baseline.open("a") as handle:
        for event_id in ("chg_1", "chg_2", "chg_3"):
            handle.write(json.dumps(_event(event_id)) + "\n")
    real_write = conversion.write_event
    calls = {"count": 0}

    def flaky(root, event):
        calls["count"] += 1
        if calls["count"] == 3:
            raise OSError("disk full")
        return real_write(root, event)

    monkeypatch.setattr(conversion, "write_event", flaky)
    with pytest.raises(OSError):
        ledger_api.convert_legacy_baseline(tmp_path, "HEAD")
    assert event_path(tmp_path, "chg_1").is_file() and event_path(tmp_path, "chg_2").is_file()
    assert not event_path(tmp_path, "chg_3").exists() and baseline.read_text() != original  # baseline not yet restored
    monkeypatch.setattr(conversion, "write_event", real_write)

    result = ledger_api.convert_legacy_baseline(tmp_path, "HEAD")

    assert result["restored"] is True and baseline.read_text() == original
    assert [e["event-id"] for e in iter_events(tmp_path)] == ["chg_old", "chg_1", "chg_2", "chg_3"]
