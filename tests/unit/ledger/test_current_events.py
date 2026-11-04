"""The per-event store: write-once files, one loader, release by historical id, real git merges."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from audiagentic.components.ledger import ledger_api
from audiagentic.components.ledger.current_events import (
    anomalies,
    event_file_name,
    event_path,
    iter_events,
    pending_events,
)
from audiagentic.components.ledger.recorder import record_change_event
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _event(event_id: str, summary: str = "s", **extra) -> dict:
    return {"event-id": event_id, "timestamp-utc": "2026-11-01T00:00:00Z", "change-class": "feature",
            "files": ["src/a.py"], "technical-summary": summary, "user-summary-candidate": summary,
            "status": "unreleased", **extra}


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          capture_output=True, text=True, check=True)
    return done.stdout


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "README.md").write_text("x\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_the_event_file_is_named_by_the_digest_of_its_id(tmp_path: Path) -> None:
    record_change_event(tmp_path, _event("chg_a'(x),1"))
    assert event_path(tmp_path, "chg_a'(x),1").name == hashlib.sha256(b"chg_a'(x),1").hexdigest() + ".json"
    assert event_path(tmp_path, "chg_a'(x),1").is_file()


def test_the_same_event_is_idempotent_and_different_content_is_refused(tmp_path: Path) -> None:
    assert record_change_event(tmp_path, _event("chg_x"))["status"] == "created"
    assert record_change_event(tmp_path, _event("chg_x"))["status"] == "exists"
    with pytest.raises(AudiaGenticError, match="different content"):
        record_change_event(tmp_path, _event("chg_x", "changed"))


def test_a_recorded_event_must_be_current(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError):
        record_change_event(tmp_path, _event("chg_rel", status="released", **{"release-id": "r1"}))


def test_a_renamed_or_corrupt_event_file_fails_closed(tmp_path: Path) -> None:
    record_change_event(tmp_path, _event("chg_ok"))
    path = event_path(tmp_path, "chg_ok")
    path.rename(path.with_name("0" * 64 + ".json"))
    with pytest.raises(AudiaGenticError, match="does not match"):
        iter_events(tmp_path)
    (path.with_name("0" * 64 + ".json")).write_text("{not json")
    with pytest.raises(AudiaGenticError):
        iter_events(tmp_path)


def test_loader_order_is_baseline_then_events_by_timestamp_and_id(tmp_path: Path) -> None:
    baseline = tmp_path / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(json.dumps(_event("chg_old")) + "\n")
    record_change_event(tmp_path, _event("chg_b", **{"timestamp-utc": "2026-11-02T00:00:00Z"}))
    record_change_event(tmp_path, _event("chg_c", **{"timestamp-utc": "2026-11-01T00:00:00Z"}))
    record_change_event(tmp_path, _event("chg_a", **{"timestamp-utc": "2026-11-02T00:00:00Z"}))
    assert [e["event-id"] for e in iter_events(tmp_path)] == ["chg_old", "chg_c", "chg_a", "chg_b"]


def test_an_id_in_both_sources_must_be_identical(tmp_path: Path) -> None:
    baseline = tmp_path / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(json.dumps(_event("chg_dup", "one")) + "\n")
    record_change_event(tmp_path, _event("chg_dup", "one"))
    assert [e["event-id"] for e in iter_events(tmp_path)] == ["chg_dup"]  # one event, not two
    event_path(tmp_path, "chg_dup").write_text(json.dumps(_event("chg_dup", "two")))
    with pytest.raises(AudiaGenticError, match="different content"):
        iter_events(tmp_path)


def test_legacy_anomalies_load_unchanged_with_deterministic_ids_and_are_reported(tmp_path: Path) -> None:
    baseline = tmp_path / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    baseline.parent.mkdir(parents=True)
    no_id = {"change-class": "feat", "files": ["a"], "technical-summary": "t", "user-summary-candidate": "u",
             "status": "unreleased", "timestamp-utc": "2026-01-01T00:00:00Z"}
    no_summary = {"event-id": "chg_ns", "change-class": "docs", "files": ["a"], "technical-summary": "t",
                  "status": "unreleased"}
    baseline.write_text(json.dumps(no_id) + "\n" + json.dumps(no_summary) + "\n")
    first, second = iter_events(tmp_path)
    assert first["event-id"].startswith("legacy-line-1-") and first["change-class"] == "feat"
    assert iter_events(tmp_path)[0]["event-id"] == first["event-id"]  # stable across reads
    assert "timestamp-utc" not in second  # unchanged: nothing is invented
    kinds = {(a["event-id"], a["kind"]) for a in anomalies(tmp_path)}
    assert (first["event-id"], "synthetic event-id") in kinds and (first["event-id"], "unknown change-class") in kinds
    assert ("chg_ns", "missing timestamp") in kinds and ("chg_ns", "missing user-summary-candidate") in kinds


def test_the_historical_ledger_is_authoritative_a_released_event_is_never_pending(tmp_path: Path) -> None:
    record_change_event(tmp_path, _event("chg_new"))
    record_change_event(tmp_path, _event("chg_released"))
    historical = tmp_path / "docs" / "releases" / "LEDGER.ndjson"
    historical.write_text(json.dumps({**_event("chg_released"), "status": "released", "release-id": "r1"}) + "\n")
    assert [e["event-id"] for e in pending_events(tmp_path)] == ["chg_new"]
    historical.write_text(json.dumps({**_event("chg_released", "other"), "status": "released", "release-id": "r1"}) + "\n")
    with pytest.raises(AudiaGenticError, match="conflicting content"):
        pending_events(tmp_path)


def test_release_writes_only_the_historical_ledger_and_is_idempotent(tmp_path: Path) -> None:
    record_change_event(tmp_path, _event("chg_1"))
    baseline = tmp_path / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    baseline.write_text(json.dumps(_event("chg_0")) + "\n")
    before = {p: p.read_bytes() for p in (baseline, event_path(tmp_path, "chg_1"))}

    first = ledger_api.archive_for_release(tmp_path, "rel_1")
    record_change_event(tmp_path, _event("chg_2"))  # recorded after the release started
    retry = ledger_api.archive_for_release(tmp_path, "rel_1")

    assert first["released-event-ids"] == ["chg_0", "chg_1"]
    assert retry["idempotent-retry"] is True and retry["released-event-ids"] == ["chg_0", "chg_1"]
    assert {p: p.read_bytes() for p in before} == before  # no event file or baseline was edited or deleted
    assert [e["event-id"] for e in pending_events(tmp_path)] == ["chg_2"]  # the next release's event is preserved
    assert ledger_api.archive_for_release(tmp_path, "rel_2")["released-event-ids"] == ["chg_2"]


def test_a_stale_branch_cannot_resurrect_a_released_event(tmp_path: Path) -> None:
    record_change_event(tmp_path, _event("chg_1"))
    ledger_api.archive_for_release(tmp_path, "rel_1")
    # A stale branch brings the same event file back (a re-recording is idempotent) and an outbox intent.
    record_change_event(tmp_path, _event("chg_1"))
    assert pending_events(tmp_path) == []


def test_archive_refuses_a_legacy_row_the_strict_contract_rejects(tmp_path: Path) -> None:
    baseline = tmp_path / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(json.dumps({**_event("chg_legacy"), "change-class": "perf"}) + "\n")
    with pytest.raises(AudiaGenticError):
        ledger_api.archive_for_release(tmp_path, "rel_1")
    assert not (tmp_path / "docs" / "releases" / "LEDGER.ndjson").exists()


def test_two_branches_that_record_different_events_merge_in_either_order_with_no_driver(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "one")
    record_change_event(repo, _event("chg_one"))
    _commit(repo, "one")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "two")
    record_change_event(repo, _event("chg_two"))
    _commit(repo, "two")
    for first, second in (("one", "two"), ("two", "one")):
        _git(repo, "checkout", "-q", "-B", f"merge-{first}", "main")
        _git(repo, "merge", "-q", "--no-edit", first)
        _git(repo, "merge", "-q", "--no-edit", second)  # raises on any conflict
        assert {e["event-id"] for e in iter_events(repo)} == {"chg_one", "chg_two"}


def test_a_release_between_branch_creation_and_merge_does_not_conflict(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    record_change_event(repo, _event("chg_base"))
    _commit(repo, "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    record_change_event(repo, _event("chg_feature"))
    _commit(repo, "feature")
    _git(repo, "checkout", "-q", "main")
    ledger_api.archive_for_release(repo, "rel_1")  # finalize on main: writes only LEDGER.ndjson (+ summary)
    _commit(repo, "release")
    _git(repo, "merge", "-q", "--no-edit", "feature")
    assert [e["event-id"] for e in pending_events(repo)] == ["chg_feature"]


def test_reading_at_a_git_ref_matches_the_working_tree_at_that_ref(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    baseline = repo / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(json.dumps(_event("chg_old")) + "\n")
    record_change_event(repo, _event("chg_one"))
    _commit(repo, "one")
    _git(repo, "tag", "v1")
    record_change_event(repo, _event("chg_two"))
    _commit(repo, "two")
    sha = _git(repo, "rev-parse", "v1").strip()
    expected = [e["event-id"] for e in iter_events(repo, ref="v1")]
    assert expected == ["chg_old", "chg_one"] == [e["event-id"] for e in iter_events(repo, ref=sha)]
    assert [e["event-id"] for e in iter_events(repo)] == ["chg_old", "chg_one", "chg_two"]
    assert [e["event-id"] for e in pending_events(repo, ref="v1")] == ["chg_old", "chg_one"]
    with pytest.raises(AudiaGenticError):
        iter_events(repo, ref="no-such-ref")


def test_ids_cannot_escape_the_events_directory(tmp_path: Path) -> None:
    for bad in ("../evil", "a/b", ".."):
        with pytest.raises(AudiaGenticError):
            record_change_event(tmp_path, _event(bad))
    assert event_file_name("../evil").endswith(".json") and "/" not in event_file_name("../evil")


def test_recording_a_released_id_with_different_content_is_refused_before_any_file_is_written(tmp_path: Path) -> None:
    historical = tmp_path / "docs" / "releases" / "LEDGER.ndjson"
    historical.parent.mkdir(parents=True)
    historical.write_text(json.dumps({**_event("chg_r"), "status": "released", "release-id": "r1"}) + "\n")
    with pytest.raises(AudiaGenticError, match="already released"):
        record_change_event(tmp_path, _event("chg_r", "different"))
    assert not event_path(tmp_path, "chg_r").exists()
    assert pending_events(tmp_path) == []  # the ledger stays readable


def test_a_crash_before_the_historical_write_leaves_the_release_unarchived_and_the_retry_completes_it(
        tmp_path: Path, monkeypatch) -> None:
    from audiagentic.components.ledger import archive

    record_change_event(tmp_path, _event("chg_1"))
    real = archive.atomic_write_ndjson

    def crash(*args, **kwargs):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(archive, "atomic_write_ndjson", crash)
    with pytest.raises(RuntimeError):
        ledger_api.archive_for_release(tmp_path, "rel_1")
    assert not (tmp_path / "docs" / "releases" / "LEDGER.ndjson").exists()  # nothing half-released
    monkeypatch.setattr(archive, "atomic_write_ndjson", real)

    assert ledger_api.archive_for_release(tmp_path, "rel_1")["released-event-ids"] == ["chg_1"]
    assert (tmp_path / "docs" / "releases" / "CURRENT_RELEASE.md").is_file()


def test_a_duplicated_conflicting_historical_id_fails_closed_even_on_a_retry(tmp_path: Path) -> None:
    record_change_event(tmp_path, _event("chg_1"))
    ledger_api.archive_for_release(tmp_path, "rel_1")
    historical = tmp_path / "docs" / "releases" / "LEDGER.ndjson"
    released = {**_event("chg_1"), "status": "released", "release-id": "rel_1"}
    historical.write_text(json.dumps(released) + "\n" + json.dumps({**released, "technical-summary": "x"}) + "\n")
    with pytest.raises(AudiaGenticError):
        ledger_api.archive_for_release(tmp_path, "rel_1")


def test_a_symlinked_or_nested_event_file_is_refused_or_ignored_the_same_in_tree_and_ref(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    record_change_event(repo, _event("chg_ok"))
    nested = repo / "docs" / "releases" / "events" / "sub"
    nested.mkdir()
    (nested / ("a" * 64 + ".json")).write_text(json.dumps(_event("chg_nested")))
    _commit(repo, "with nested")
    assert [e["event-id"] for e in iter_events(repo)] == ["chg_ok"]
    assert [e["event-id"] for e in iter_events(repo, ref="HEAD")] == ["chg_ok"]  # same set, tree and ref
    link = repo / "docs" / "releases" / "events" / (hashlib.sha256(b"chg_link").hexdigest() + ".json")
    link.symlink_to(event_path(repo, "chg_ok"))
    with pytest.raises(AudiaGenticError, match="regular file"):
        iter_events(repo)


def test_the_outbox_still_delivers_a_projection_for_an_event_that_is_already_released(tmp_path: Path) -> None:
    from audiagentic.components.ledger import event_outbox

    event = _event("chg_rel", **{"plan-item-ids": ["TST01"]})
    historical = tmp_path / "docs" / "releases" / "LEDGER.ndjson"
    historical.parent.mkdir(parents=True)
    historical.write_text(json.dumps({**event, "status": "released", "release-id": "r1"}) + "\n")
    event_outbox.enqueue(tmp_path, "chg_rel", ["TST01"], event=event)
    delivered: list[str] = []

    result = event_outbox.drain(tmp_path, publisher=lambda event_id, *a, **k: delivered.append(event_id))

    assert result == {"delivered": 1, "failed": 0} and delivered == ["chg_rel"]
    assert not event_path(tmp_path, "chg_rel").exists()  # never resurrected as a pending event file


def test_stamping_touches_only_event_files_the_commit_introduced(tmp_path: Path, monkeypatch) -> None:
    from audiagentic.components.source_control import source_control_bootstrap
    from audiagentic.components.source_control.git_commits import stamp_ledger_for_commit

    monkeypatch.setattr(source_control_bootstrap, "post_commit_ledger_stamp_enabled", lambda root: True)

    repo = _repo(tmp_path)
    record_change_event(repo, _event("chg_old", files=["src/a.py"]))
    _commit(repo, "old event")
    old = event_path(repo, "chg_old").read_text()
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("x\n")
    record_change_event(repo, _event("chg_new", files=["src/a.py"]))
    _commit(repo, "new event and code")

    stamped = stamp_ledger_for_commit(repo)

    assert list(stamped.values()) == [["chg_new"]]
    assert event_path(repo, "chg_old").read_text() == old  # an earlier, shared event file is never rewritten
    assert "git-commits" in json.loads(event_path(repo, "chg_new").read_text())


def test_the_store_scales_to_thousands_of_events(tmp_path: Path) -> None:
    import time

    from audiagentic.components.ledger.current_events import event_text

    events_dir = tmp_path / "docs" / "releases" / "events"
    events_dir.mkdir(parents=True)
    for index in range(3000):
        event = _event(f"chg_{index:05d}", files=[f"src/f{index % 50}.py"], **{"plan-item-ids": [f"P{index % 40}"]})
        (events_dir / event_file_name(event["event-id"])).write_text(event_text(event))
    started = time.monotonic()
    assert len(pending_events(tmp_path)) == 3000
    grouped = ledger_api.get_pending_events(tmp_path)
    assert time.monotonic() - started < 20 and grouped["groups"]
