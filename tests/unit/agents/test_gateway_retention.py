from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.helpers.gateway_settings import use_gateway_settings

from audiagentic.components.agents.agents_paths import gateway_request_dir, gateway_timeline_path
from audiagentic.components.agents.gateway import retention
from audiagentic.components.agents.gateway.operations.retention_policy import (
    DEFAULT_CONSOLE_TRACE_MAX_BYTES,
    DEFAULT_OBSERVATION_MAX_BYTES,
    DEFAULT_RECOVERY_MAX_BYTES,
    DEFAULT_REQUEST_HISTORY_LIMIT,
    DEFAULT_TIMELINE_MAX_BYTES,
    load_retention_policy,
)
from audiagentic.components.agents.gateway.retention import (
    compact_indexed_ndjson,
    enforce_request_retention,
)
from audiagentic.components.agents.gateway.session.console_trace import GatewayConsoleTrace


def test_pending_terminal_handoff_is_not_retention_eligible(tmp_path, monkeypatch):
    request_id = "req_pending_handoff"
    directory = gateway_request_dir(tmp_path, request_id)
    directory.mkdir(parents=True)
    record = {"request-id": request_id, "state": "completed", "terminal-finalization": {"pre-clear-checkpoint": {"unresolved-turn-id": request_id}}}
    path = directory / "record.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(retention, "request_retention_pin", lambda *_: SimpleNamespace(pinned=False))
    assert retention._eligible_record(tmp_path, directory) is None
    record.pop("terminal-finalization")
    path.write_text(json.dumps(record), encoding="utf-8")
    assert retention._eligible_record(tmp_path, directory) is not None


@pytest.mark.parametrize("has_runtime_file", [True, False])
def test_positive_runtime_pin_skips_global_session_census(tmp_path, monkeypatch, has_runtime_file):
    directory = gateway_request_dir(tmp_path, "req_runtime_pin")
    (directory / "runtime").mkdir(parents=True)
    (directory / "record.json").write_text(json.dumps({
        "request-id": "req_runtime_pin", "state": "completed",
    }), encoding="utf-8")
    if has_runtime_file:
        (directory / "runtime" / "admitted-prompt.txt").write_text("saved prompt", encoding="utf-8")
    calls = []

    def full_census(*_args):
        calls.append(True)
        return SimpleNamespace(pinned=False)

    monkeypatch.setattr(retention, "request_retention_pin", full_census)
    result = retention._eligible_record(tmp_path, directory)
    assert (result is None) is has_runtime_file
    assert len(calls) == int(not has_runtime_file)


def test_positive_lineage_snapshot_only_skips_known_kept_requests(tmp_path, monkeypatch):
    directory = gateway_request_dir(tmp_path, "req_lineage_pin")
    directory.mkdir(parents=True)
    (directory / "record.json").write_text(json.dumps({
        "request-id": "req_lineage_pin", "state": "completed",
    }), encoding="utf-8")
    calls = []
    monkeypatch.setattr(retention, "request_retention_pin", lambda *_: (calls.append(True) or SimpleNamespace(pinned=True)))
    assert retention._eligible_record(tmp_path, directory, positive_lineage=frozenset({"req_lineage_pin"})) is None
    assert not calls
    assert retention._eligible_record(tmp_path, directory, positive_lineage=frozenset({"some_other_request"})) is None
    assert calls == [True]  # Missing snapshot entries still need fresh pin authority.


def test_positive_lineage_snapshot_contains_only_durable_string_references(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway.session import retention as session_retention
    monkeypatch.setattr(session_retention, "list_session_records", lambda *_: [
        {"activity": {"request-ids": ["req_one", "req_one", "", None, 1]}},
        {"activity": {"request-ids": ["req_two"]}}, {"activity": None},
    ])
    assert session_retention.positive_session_lineage_snapshot(tmp_path) == frozenset({"req_one", "req_two"})


def test_failed_lineage_census_skips_maintenance(tmp_path, monkeypatch):
    from audiagentic.components.agents.gateway.session import retention as session_retention
    gateway_request_dir(tmp_path, "req_protected").mkdir(parents=True)

    def failed(*_args):
        raise OSError("unreadable session census")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("failed census must not proceed with maintenance")

    monkeypatch.setattr(session_retention, "positive_session_lineage_snapshot", failed)
    monkeypatch.setattr(retention, "_eligible_record", forbidden)
    assert retention.enforce_request_retention(tmp_path)["compacted"] == 0


def test_retention_policy_defaults_and_machine_overrides(tmp_path: Path, monkeypatch) -> None:
    default = load_retention_policy()
    assert default.request_history_limit == DEFAULT_REQUEST_HISTORY_LIMIT
    assert default.timeline_max_bytes == DEFAULT_TIMELINE_MAX_BYTES
    assert default.observation_max_bytes == DEFAULT_OBSERVATION_MAX_BYTES
    assert default.recovery_max_bytes == DEFAULT_RECOVERY_MAX_BYTES
    assert default.console_trace_max_bytes == DEFAULT_CONSOLE_TRACE_MAX_BYTES

    use_gateway_settings(
        monkeypatch, tmp_path,
        retention={
            "policy_id": "ops",
            "request_history_limit": 7,
            "timeline_max_bytes": 700,
            "observation_max_bytes": 800,
            "recovery_max_bytes": 900,
            "console_trace_max_bytes": 1000,
        },
    )
    configured = load_retention_policy()
    assert configured.available is True
    assert configured.request_history_limit == 7
    assert configured.timeline_max_bytes == 700
    assert configured.observation_max_bytes == 800
    assert configured.recovery_max_bytes == 900
    assert configured.console_trace_max_bytes == 1000


def test_indexed_compaction_preserves_terminal_evidence_and_rebuilds_offsets(tmp_path: Path) -> None:
    journal = tmp_path / "timeline.ndjson"
    index = tmp_path / "timeline.index.ndjson"
    rows = [
        {"event": "old", "state": "running", "payload": "x" * 90},
        {"event": "terminal", "state": "completed", "payload": "evidence"},
        {"event": "latest", "state": "running", "payload": "tail"},
    ]
    journal.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    index.write_text("{}\n{}\n{}\n", encoding="utf-8")

    assert compact_indexed_ndjson(
        journal,
        index,
        max_bytes=240,
        preserve=lambda row: row.get("state") == "completed",
    )
    compacted = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in compacted] == ["terminal", "latest"]
    assert journal.stat().st_size <= 350

    offset = 0
    for line, metadata_line in zip(journal.read_bytes().splitlines(keepends=True), index.read_bytes().splitlines()):
        metadata = json.loads(metadata_line)
        assert metadata["offset"] == offset
        assert metadata["length"] == len(line)
        offset += len(line)


def test_compaction_leaves_room_for_following_appends(tmp_path: Path) -> None:
    journal = tmp_path / "timeline.ndjson"
    index = tmp_path / "timeline.index.ndjson"
    rows = [{"event": str(number), "payload": "x" * 100} for number in range(100)]
    journal.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    assert compact_indexed_ndjson(journal, index, max_bytes=4000)
    assert journal.stat().st_size <= 3000
    assert json.loads(journal.read_text().splitlines()[-1])["event"] == "99"
    with journal.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"event": "next"}) + "\n")
    assert not compact_indexed_ndjson(journal, index, max_bytes=4000)


def test_rolling_retention_compacts_old_resolved_histories_without_deleting_directories(tmp_path: Path, monkeypatch) -> None:
    use_gateway_settings(monkeypatch, tmp_path, retention={"request_history_limit": 1, "timeline_max_bytes": 500})
    request_ids = ["req_old", "req_middle", "req_new"]
    for index, request_id in enumerate(request_ids):
        request_dir = gateway_request_dir(tmp_path, request_id)
        request_dir.mkdir(parents=True)
        (request_dir / "record.json").write_text(
            json.dumps(
                {
                    "request-id": request_id,
                    "state": "completed",
                    "finished-at": f"2026-10-{10 + index:02d}T00:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        timeline = gateway_timeline_path(tmp_path, request_id)
        timeline.write_text(
            "".join(json.dumps({"event": f"event-{item}", "state": "running", "payload": "x" * 120}) + "\n" for item in range(8))
            + json.dumps({"event": "terminal", "state": "completed"}) + "\n",
            encoding="utf-8",
        )

    result = enforce_request_retention(tmp_path)

    assert result["limit"] == 1
    assert result["eligible"] == 3
    assert result["compacted"] >= 2
    assert all(gateway_request_dir(tmp_path, request_id).exists() for request_id in request_ids)
    assert all(gateway_request_dir(tmp_path, request_id).joinpath("record.json").exists() for request_id in request_ids)


def test_terminal_timeline_schedules_retention_instead_of_running_inline(tmp_path: Path, monkeypatch) -> None:
    from audiagentic.components.agents.gateway.store import _shared

    scheduled: list[tuple[Path, str | None]] = []
    monkeypatch.setattr(
        retention,
        "schedule_request_retention",
        lambda root, *, trigger_request_id=None: scheduled.append((root, trigger_request_id)),
    )
    monkeypatch.setattr(
        retention,
        "enforce_request_retention",
        lambda *_args, **_kwargs: pytest.fail("retention must not execute inline"),
    )

    _shared.record_gateway_timeline(
        tmp_path,
        "req_terminal_retention_async",
        "state.changed",
        state="completed",
    )

    assert scheduled == [(tmp_path, "req_terminal_retention_async")]


def test_background_retention_sweep_records_duration_and_result(tmp_path: Path, monkeypatch) -> None:
    record = gateway_request_dir(tmp_path, "req_retention_trace") / "record.json"
    record.parent.mkdir(parents=True)
    record.write_text('{"request-id":"req_retention_trace","state":"completed"}', encoding="utf-8")
    observed: list[dict] = []
    threads: list[SimpleNamespace] = []

    class FakeThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            threads.append(SimpleNamespace(target=self.target))

    from audiagentic.components.agents.gateway import observability

    monkeypatch.setattr(retention.threading, "Thread", FakeThread)
    monkeypatch.setattr(
        retention,
        "enforce_request_retention",
        lambda _root: {
            "limit": 100,
            "eligible": 120,
            "retained": 100,
            "compacted": 20,
            "protected": 0,
        },
    )
    monkeypatch.setattr(
        observability,
        "append_observation",
        lambda _root, _request_id, **kwargs: observed.append(kwargs),
    )

    assert retention.schedule_request_retention(
        tmp_path, trigger_request_id="req_retention_trace"
    )
    assert len(threads) == 1
    threads[0].target()

    assert len(observed) == 1
    event = observed[0]
    assert event["source"] == "request-retention"
    assert event["action"]["outcome"] == "completed"
    assert event["diagnostic_facts"]["retention"]["sweep-result"]["compacted"] == 20
    assert event["diagnostic_facts"]["retention"]["sweep-duration-ms"] >= 0
    assert retention._RETENTION_WORKER_RUNNING is False


def test_console_trace_rotates_one_bounded_backup(tmp_path: Path, monkeypatch) -> None:
    use_gateway_settings(monkeypatch, tmp_path, console_trace={"mode": "summary"}, retention={"console_trace_max_bytes": 400})
    path = tmp_path / "console-trace.log"
    stream = path.open("a", encoding="utf-8", buffering=1)
    trace = GatewayConsoleTrace(stream=stream)
    for index in range(8):
        trace.session_opened(
            session_id=f"ses_{index}",
            provider_id="codex",
            model_id="model",
            execution_profile_id="profile",
            surface_id="surface",
            child_pid=index,
        )
    assert trace.stream is not None
    trace.stream.close()

    backup = path.with_name(path.name + ".1")
    assert backup.exists()
    assert path.stat().st_size <= 400
    assert backup.stat().st_size <= 400


def test_console_trace_never_turns_a_capture_wrapper_name_into_a_file(tmp_path: Path, monkeypatch) -> None:
    """pytest's stderr reports a repr like "<_io.FileIO name=8 ...>" as its name; that is not a path."""
    import io

    class _CaptureLike(io.StringIO):
        name = "<_io.FileIO name=8 mode='rb+' closefd=True>"

    use_gateway_settings(monkeypatch, tmp_path, console_trace={"mode": "summary"}, retention={"console_trace_max_bytes": 1})
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    stream = _CaptureLike()
    trace = GatewayConsoleTrace(stream=stream)
    for index in range(3):  # a 1-byte cap would force a rotation attempt on every line
        trace.session_opened(
            session_id=f"ses_{index}", provider_id="codex", model_id="model",
            execution_profile_id="profile", surface_id="surface", child_pid=index,
        )
    assert list(workdir.iterdir()) == []  # nothing was created in the working directory
    assert trace.stream is stream
    assert "ses_2" in stream.getvalue()  # and the lines still reached the stream
