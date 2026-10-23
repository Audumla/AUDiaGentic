from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from audiagentic.foundation.io import iter_ndjson, last_ndjson, tail_ndjson
from audiagentic.foundation.observability import journal_segments as segments

DAY = datetime(2026, 10, 1, tzinfo=timezone.utc)


def append(path: Path, number: int, *, now=DAY, cap=1000, payload=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    index = path.with_suffix(".index.ndjson")
    line = json.dumps({"event_seq": number, "payload": payload}) + "\n"
    with segments.journal_lock(path):
        segments.prepare_append(
            path, index, max_bytes=cap, incoming_bytes=len(line.encode()), now=now
        )
        offset = path.stat().st_size if path.exists() else 0
        with path.open("a", encoding="utf-8") as stream:
            stream.write(line)
        with index.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event_seq": number, "offset": offset}) + "\n")
        os.utime(path, (now.timestamp(), now.timestamp()))


def test_daily_rollover_and_compressed_history_are_transparent(tmp_path):
    path = tmp_path / "observations.ndjson"
    append(path, 1)
    append(path, 2, now=DAY + timedelta(days=1))
    assert len(segments.segment_paths(path)) == 1
    assert segments.maintain_segments(path, delete_before=None) == {
        "compressed": 1,
        "deleted": 0,
        "temporary-deleted": 0,
    }
    assert segments.segment_paths(path)[0].suffix == ".gz"
    assert [row["event_seq"] for row in iter_ndjson(path)] == [1, 2]
    assert last_ndjson(path)["event_seq"] == 2
    assert [row["event_seq"] for row in tail_ndjson(path, 2)] == [1, 2]


def test_size_rollover_keeps_oversized_single_records_intact(tmp_path):
    path = tmp_path / "timeline.ndjson"
    for number in range(3):
        append(path, number, cap=40, payload="x" * 100)
    assert len(segments.segment_paths(path)) == 2
    assert [row["event_seq"] for row in iter_ndjson(path)] == [0, 1, 2]
    assert all(len(row["payload"]) == 100 for row in iter_ndjson(path))


def test_expiry_uses_last_write_time_and_preserves_head(tmp_path):
    path = tmp_path / "timeline.ndjson"
    append(path, 1)
    append(path, 2, now=DAY + timedelta(days=1))
    segments.maintain_segments(path, delete_before=None)
    archived = segments.segment_paths(path)[0]
    assert archived.stat().st_mtime == DAY.timestamp()
    cutoff = (DAY + timedelta(days=5)).timestamp()
    assert segments.maintain_segments(path, delete_before=cutoff)["deleted"] == 1
    assert last_ndjson(path)["event_seq"] == 2


def test_restart_adopts_existing_head_and_rebuilds_new_index(tmp_path):
    path = tmp_path / "timeline.ndjson"
    path.write_text('{"event_seq":1}\n', encoding="utf-8")
    os.utime(path, (DAY.timestamp(), DAY.timestamp()))
    append(path, 2, now=DAY + timedelta(days=1))
    assert len(segments.segment_paths(path)) == 1
    assert json.loads(path.with_suffix(".index.ndjson").read_text())["offset"] == 0
    assert [row["event_seq"] for row in iter_ndjson(path)] == [1, 2]


def test_bad_rotation_day_cannot_escape_storage_directory(tmp_path):
    path = tmp_path / "timeline.ndjson"
    append(path, 1)
    path.with_name(path.name + ".rotation.json").write_text('{"utc-day":"../../escape"}')
    with pytest.raises(ValueError):
        append(path, 2)
    assert not (tmp_path.parent / "escape").exists()


def test_unknown_segment_files_are_never_cleanup_targets(tmp_path):
    path = tmp_path / "timeline.ndjson"
    append(path, 1)
    directory = segments.segment_directory(path)
    directory.mkdir()
    unknown = directory / "output.txt"
    unknown.write_text("keep")
    segments.maintain_segments(path, delete_before=float("inf"))
    assert unknown.read_text() == "keep"


def test_compression_failure_keeps_plain_source(tmp_path, monkeypatch):
    path = tmp_path / "timeline.ndjson"
    append(path, 1)
    append(path, 2, now=DAY + timedelta(days=1))

    def fail(**kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(segments.gzip, "GzipFile", fail)
    with pytest.raises(OSError):
        segments.maintain_segments(path, delete_before=None)
    assert segments.segment_paths(path)[0].suffix == ".ndjson"
    assert not list(segments.segment_directory(path).glob(".compress-*"))


def test_published_gzip_and_plain_copy_are_not_replayed_twice(tmp_path, monkeypatch):
    path = tmp_path / "timeline.ndjson"
    append(path, 1)
    append(path, 2, now=DAY + timedelta(days=1))
    source = segments.segment_paths(path)[0]
    real_unlink = Path.unlink

    def interrupted_unlink(candidate, *args, **kwargs):
        if candidate == source:
            raise OSError("interrupted after gzip publication")
        return real_unlink(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", interrupted_unlink)
    with pytest.raises(OSError):
        segments.maintain_segments(path, delete_before=None)
    assert source.exists()
    assert [row["event_seq"] for row in iter_ndjson(path)] == [1, 2]


def test_concurrent_writers_and_compression_preserve_all_rows(tmp_path):
    path = tmp_path / "timeline.ndjson"

    def write(number):
        append(path, number, cap=200)
        if number % 7 == 0:
            segments.maintain_segments(path, delete_before=None)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(40)))
    rows = list(iter_ndjson(path))
    assert sorted(row["event_seq"] for row in rows) == list(range(40))


def test_reentrant_lock_allows_writer_sequence_reads(tmp_path):
    path = tmp_path / "observations.ndjson"
    append(path, 1)
    with segments.journal_lock(path):
        assert last_ndjson(path)["event_seq"] == 1


def test_maintenance_batch_is_bounded(tmp_path):
    path = tmp_path / "timeline.ndjson"
    for number in range(5):
        append(path, number, cap=1)
    result = segments.maintain_segments(path, delete_before=None, max_operations=2)
    assert result == {"compressed": 2, "deleted": 0, "temporary-deleted": 0}


def test_crash_temporary_cleanup_is_owned_and_bounded(tmp_path):
    path = tmp_path / "timeline.ndjson"
    append(path, 1, cap=1)
    append(path, 2, cap=1)
    directory = segments.segment_directory(path)
    for suffix in ("abcd1234", "abcd1235"):
        (directory / (".compress-" + suffix)).write_text("unfinished gzip")
    unrelated = directory / ".compress-operator-notes"
    unrelated.write_text("not owned")
    result = segments.maintain_segments(path, delete_before=None, max_operations=1)
    assert result["temporary-deleted"] == 1
    assert unrelated.exists()
    assert len(list(directory.glob(".compress-abcd*"))) == 1


def test_utc_boundary_not_local_calendar_drives_rotation(tmp_path):
    path = tmp_path / "timeline.ndjson"
    append(path, 1)
    append(path, 2, now=datetime(2026, 10, 2, 1, tzinfo=timezone(timedelta(hours=2))))
    assert not segments.segment_paths(path)
    append(path, 3, now=DAY + timedelta(days=1))
    assert len(segments.segment_paths(path)) == 1


def test_reader_snapshot_cannot_skip_or_duplicate_a_concurrent_rollover(tmp_path):
    path = tmp_path / "timeline.ndjson"
    append(path, 1, cap=1)
    append(path, 2, cap=1)
    rows = iter_ndjson(path)
    assert next(rows)["event_seq"] == 1
    append(path, 3, cap=1)
    assert [row["event_seq"] for row in rows] == [2]
    assert [row["event_seq"] for row in iter_ndjson(path)] == [1, 2, 3]


def test_failed_metadata_publication_recovers_without_lost_rows(tmp_path, monkeypatch):
    import audiagentic.foundation.io as io

    path = tmp_path / "timeline.ndjson"
    append(path, 1)
    real_write = io.atomic_write_json

    def fail(*args, **kwargs):
        raise OSError("crash after head rename")

    monkeypatch.setattr(io, "atomic_write_json", fail)
    with pytest.raises(OSError):
        append(path, 2, now=DAY + timedelta(days=1))
    monkeypatch.setattr(io, "atomic_write_json", real_write)
    append(path, 2, now=DAY + timedelta(days=1))
    assert [row["event_seq"] for row in iter_ndjson(path)] == [1, 2]


def test_slow_compression_does_not_hold_writer_fence(tmp_path, monkeypatch):
    path = tmp_path / "timeline.ndjson"
    append(path, 1, cap=1)
    append(path, 2, cap=1)
    copying = threading.Event()
    release = threading.Event()
    real_copy = segments.shutil.copyfileobj

    def slow_copy(*args, **kwargs):
        copying.set()
        assert release.wait(5)
        return real_copy(*args, **kwargs)

    monkeypatch.setattr(segments.shutil, "copyfileobj", slow_copy)
    with ThreadPoolExecutor(max_workers=2) as pool:
        compressor = pool.submit(segments.maintain_segments, path, delete_before=None)
        try:
            assert copying.wait(3)
            pool.submit(append, path, 3).result(timeout=2)
        finally:
            release.set()
        compressor.result(timeout=3)
    assert [row["event_seq"] for row in iter_ndjson(path)] == [1, 2, 3]


def test_segment_order_does_not_depend_on_wall_clock_advancing(tmp_path):
    path = tmp_path / "timeline.ndjson"
    append(path, 1)
    append(path, 2, now=DAY + timedelta(days=1))
    append(path, 3, now=DAY - timedelta(days=1))
    append(path, 4, now=DAY - timedelta(days=2))
    assert [row["event_seq"] for row in iter_ndjson(path)] == [1, 2, 3, 4]


def test_real_processes_share_sequence_and_rotation_fence(tmp_path):
    path = tmp_path / "observations.ndjson"
    code = """
import json, sys
from pathlib import Path
from audiagentic.foundation.io import last_ndjson
from audiagentic.foundation.observability.journal_segments import journal_lock, prepare_append
path = Path(sys.argv[1])
index = path.with_suffix('.index.ndjson')
for _ in range(20):
    with journal_lock(path):
        previous = last_ndjson(path)
        sequence = previous['event_seq'] + 1 if previous else 1
        line = json.dumps({'event_seq':sequence}) + '\\n'
        prepare_append(path, index, max_bytes=200, incoming_bytes=len(line.encode()))
        with path.open('a', encoding='utf-8') as stream:
            stream.write(line)
"""
    children = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        for _ in range(2)
    ]
    try:
        for child in children:
            _, stderr = child.communicate(timeout=20)
            assert child.returncode == 0, stderr.decode(errors="replace")
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
    assert [row["event_seq"] for row in iter_ndjson(path)] == list(range(1, 41))


def test_non_gateway_resource_timeline_keeps_its_existing_byte_bound(tmp_path):
    from audiagentic.foundation.observability.timeline import record_timeline_event

    path = tmp_path / "timeline.ndjson"
    rows = [{"event": "old", "payload": "x" * 2000} for _ in range(600)]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    record_timeline_event(
        path,
        component="foundation",
        resource_kind="service",
        resource_id="service-test",
        event="latest",
    )
    assert path.stat().st_size <= 1024 * 1024
    assert last_ndjson(path)["event"] == "latest"
    journal = path.read_bytes()
    for metadata in iter_ndjson(path.with_suffix(".index.ndjson")):
        row = json.loads(journal[metadata["offset"] : metadata["offset"] + metadata["length"]])
        assert isinstance(row, dict)
