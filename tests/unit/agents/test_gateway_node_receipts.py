"""Node-only receipt transactions, fencing and real process-death recovery."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from audiagentic.components.agents.gateway.node.receipts import NodeReceiptStore
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .test_gateway_node_contracts import authorization, identity


def child_environment():
    # Match the package under test, not a stale wheel installed in this venv.
    package_root = Path(sys.modules[NodeReceiptStore.__module__].__file__).parents[5]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(package_root) + (
        os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
    )
    return environment


def store_at(root, **changes):
    return NodeReceiptStore(
        **(
            dict(node_id="node-1", node_epoch="boot-1", gateway_owner_epoch="gateway-1", root=root)
            | changes
        )
    )


def advance(store, command=None):
    command = command or identity()
    store.prepare(command, b"payload")
    request, reply = authorization(command)
    assert store.effect_intent(command, request, reply, connection_generation=1)
    return command


def test_state_machine_exact_dedupe_and_private_output(tmp_path):
    store = store_at(tmp_path / "node")
    command = identity()
    prepared = store.prepare(command, b"payload")
    assert prepared == store.prepare(command, b"payload")
    assert prepared.sequence == 1
    request, reply = authorization(command)
    assert store.effect_intent(command, request, reply, connection_generation=1)
    assert not store.effect_intent(command, request, reply, connection_generation=1)
    accepted = store.native_accepted(command, native_ref="private://native/conversation/turn")
    assert accepted == store.native_accepted(
        command, native_ref="private://native/conversation/turn"
    )
    terminal = store.terminal(command, text="answer\nλ")
    assert terminal == store.terminal(command, text="answer\nλ")
    assert not store.effect_intent(command, request, reply, connection_generation=1)
    assert store.output(command) == "answer\nλ"
    receipts = store.receipts_after()
    assert [r.sequence for r in receipts] == [1, 2, 3, 4]
    assert [r.state for r in receipts] == [
        "prepared",
        "effect-intent",
        "native-accepted",
        "terminal",
    ]
    assert [r.sequence for r in store.receipts_after(2, limit=1)] == [3]
    wire = json.dumps([r.public_payload() for r in receipts])
    for private in ("private://", "answer", str(tmp_path), "native-ref"):
        assert private not in wire
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert db.execute("SELECT native_ref FROM commands").fetchone()[0].startswith("private://")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM outbox")


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_id", "other"),
        ("node_epoch", "other"),
        ("gateway_owner_epoch", "other"),
        ("workspace_id", "other"),
        ("grant_revision", 2),
        ("binding_generation", 2),
        ("connection_generation", 2),
        ("execution_profile_id", "other"),
        ("payload_sha256", hashlib.sha256(b"changed").hexdigest()),
    ],
)
def test_same_command_changed_identity_conflicts(tmp_path, field, value):
    store = store_at(tmp_path / "node")
    store.prepare(identity(), b"payload")
    changed = replace(identity(), **{field: value})
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        store.prepare(changed, b"changed" if field == "payload_sha256" else b"payload")
    assert len(store.receipts_after()) == 1


def test_bad_digest_no_record_and_distinct_identical_payloads_are_distinct(tmp_path):
    store = store_at(tmp_path / "node")
    with pytest.raises(AudiaGenticError):
        store.prepare(identity(), b"not payload")
    assert store.receipts_after() == ()
    a = store.prepare(identity(), b"payload")
    b = store.prepare(identity(command_id="cmd-2"), b"payload")
    assert a.identity != b.identity
    assert b.sequence == a.sequence + 1


def test_no_skipped_states_or_changed_receipts(tmp_path):
    store = store_at(tmp_path / "node")
    command = identity()
    store.prepare(command, b"payload")
    for method, kwargs in (
        (store.native_accepted, {"native_ref": "private"}),
        (store.terminal, {"text": "answer"}),
    ):
        with pytest.raises(AudiaGenticError):
            method(command, **kwargs)
    advance(store, command)
    with pytest.raises(AudiaGenticError):
        store.terminal(command, text="answer")
    store.native_accepted(command, native_ref="private")
    with pytest.raises(AudiaGenticError):
        store.native_accepted(command, native_ref="changed")
    store.terminal(command, text="answer")
    with pytest.raises(AudiaGenticError):
        store.terminal(command, text="changed")
    assert len(store.receipts_after()) == 4


def test_old_epoch_is_query_only_and_stale_instances_are_fenced(tmp_path):
    root = tmp_path / "node"
    store = store_at(root)
    command = advance(store)
    store.advance_epoch(node_epoch="boot-2", gateway_owner_epoch="gateway-2")
    current = store_at(root, node_epoch="boot-2", gateway_owner_epoch="gateway-2")
    assert current.get(command).state == "effect-intent"
    assert store.get(command).state == "effect-intent"
    for writer in (store, current):
        with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
            writer.native_accepted(command, native_ref="private")
        with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
            writer.prepare(command, b"payload")
    with pytest.raises(AudiaGenticError):
        store.advance_epoch(node_epoch="boot-3", gateway_owner_epoch="gateway-3")
    new = identity(command_id="cmd-2", node_epoch="boot-2", gateway_owner_epoch="gateway-2")
    assert current.prepare(new, b"payload").state == "prepared"


def test_concurrent_stores_grant_only_one_effect_intent(tmp_path):
    root = tmp_path / "node"
    stores = [store_at(root) for _ in range(4)]
    command = identity()
    request, reply = authorization(command)

    def contend(store):
        store.prepare(command, b"payload")
        return store.effect_intent(command, request, reply, connection_generation=1)

    with ThreadPoolExecutor(max_workers=4) as workers:
        assert sum(workers.map(contend, stores)) == 1
    assert [r.state for r in stores[0].receipts_after()] == ["prepared", "effect-intent"]


def test_auth_mismatch_cannot_persist_intent(tmp_path):
    store = store_at(tmp_path / "node")
    store.prepare(identity(), b"payload")
    request, reply = authorization()
    with pytest.raises(AudiaGenticError):
        store.effect_intent(identity(), request, reply, connection_generation=2)
    assert store.get(identity()).state == "prepared"


def test_missing_or_corrupt_terminal_artifact_fails_closed(tmp_path):
    store = store_at(tmp_path / "node")
    command = advance(store)
    store.native_accepted(command, native_ref="private")
    receipt = store.terminal(command, text="answer")
    path = store.outputs / (receipt.output_sha256 + ".txt")
    path.write_bytes(b"corrupt")
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        store.output(command)
    path.unlink()
    with pytest.raises(AudiaGenticError, match="IO-AGND-001"):
        store.output(command)
    with pytest.raises(AudiaGenticError, match="IO-AGND-001"):
        store.get(command)
    with pytest.raises(AudiaGenticError, match="IO-AGND-001"):
        store.receipts_after()
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT state FROM commands").fetchone()[0] == "terminal"


_CHILD = r"""
import json, sys, time
from pathlib import Path
from audiagentic.components.agents.gateway.node.contracts import CommandIdentity, Frame
from audiagentic.components.agents.gateway.node.receipts import NodeReceiptStore
settings=json.loads(sys.stdin.readline())
root=Path(settings['root'])
i=CommandIdentity.from_mapping(settings['identity'])
s=NodeReceiptStore(root=root,node_id=i.node_id,node_epoch=i.node_epoch,gateway_owner_epoch=i.gateway_owner_epoch)
q=Frame.from_bytes(settings['request'].encode())
r=Frame.from_bytes(settings['reply'].encode())
stage=settings['stage']
def pause():
    (root/'ready').write_text('ready')
    while True: time.sleep(1)
s.prepare(i,b'payload')
if stage=='prepared': pause()
if stage=='uncommitted-intent':
    original=s._append
    def uncommitted(db,identity,state,output_digest=None):
        original(db,identity,state,output_digest)
        pause()
    s._append=uncommitted
if s.effect_intent(i,q,r,connection_generation=1):
    # A fake external native effect, deliberately outside the SQLite lock.
    with (root/'native-calls').open('ab') as f:
        f.write(b'one\n'); f.flush()
if stage=='effect-intent': pause()
s.native_accepted(i,native_ref='private-native-turn')
if stage=='native-accepted': pause()
if stage=='orphan-output':
    original=s._append
    def append(db,identity,state,output_digest=None):
        if state=='terminal': pause()
        return original(db,identity,state,output_digest)
    s._append=append
s.terminal(i,text='verified answer')
pause()
"""


@pytest.mark.parametrize(
    "stage,expected,count",
    [
        ("prepared", "prepared", 1),
        ("uncommitted-intent", "prepared", 1),
        ("effect-intent", "effect-intent", 2),
        ("native-accepted", "native-accepted", 3),
        ("orphan-output", "native-accepted", 3),
        ("terminal", "terminal", 4),
    ],
)
def test_hard_kill_reopen_preserves_barriers_without_repeating_native_call(
    tmp_path, stage, expected, count
):
    root = tmp_path / "node"
    command = identity()
    request, reply = authorization(command)
    child = subprocess.Popen(
        [sys.executable, "-c", _CHILD],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=child_environment(),
    )
    try:
        child.stdin.write(
            json.dumps(
                {
                    "root": str(root),
                    "identity": command.to_mapping(),
                    "request": request.to_bytes().decode(),
                    "reply": reply.to_bytes().decode(),
                    "stage": stage,
                }
            )
            + "\n"
        )
        child.stdin.flush()
        deadline = time.monotonic() + 10
        while (
            not (root / "ready").exists() and child.poll() is None and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        if not (root / "ready").exists():
            child.kill()
            _, error = child.communicate(timeout=5)
            pytest.fail("Child never reached persistence barrier: " + error)
        child.kill()
        child.communicate(timeout=5)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)
    store = store_at(root)
    assert store.get(command).state == expected
    assert store.authorization_id(command) == (None if expected == "prepared" else "grant-1")
    assert len(store.receipts_after()) == count
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    if expected == "prepared":
        assert store.effect_intent(command, request, reply, connection_generation=1)
        assert not (root / "native-calls").exists()
    else:
        assert not store.effect_intent(command, request, reply, connection_generation=1)
        assert (root / "native-calls").read_bytes() == b"one\n"
    if stage == "orphan-output":
        assert store.terminal(command, text="verified answer").state == "terminal"
    if stage == "terminal":
        assert store.output(command) == "verified answer"


def test_registered_errors_and_private_root(tmp_path):
    from audiagentic.foundation.io import load_yaml_file

    codes = load_yaml_file(
        Path(__file__).parents[3]
        / "src/audiagentic/config/components/agents/error-resolutions.yaml"
    )
    assert {"VAL-AGND-001", "CON-AGND-001", "IO-AGND-001"} <= codes.keys()
    with pytest.raises(AudiaGenticError, match="VAL-AGND-001"):
        store_at(Path("relative"))
    if os.name == "posix":
        root = tmp_path / "public"
        root.mkdir(mode=0o755)
        with pytest.raises(AudiaGenticError, match="VAL-AGND-001"):
            store_at(root)


@pytest.mark.parametrize("stage", ["prepared", "effect-intent", "native-accepted", "terminal"])
def test_reboot_preserves_old_epoch_evidence_without_new_effect_authority(tmp_path, stage):
    root = tmp_path / "node"
    store = store_at(root)
    command = identity()
    store.prepare(command, b"payload")
    request, reply = authorization(command)
    if stage != "prepared":
        assert store.effect_intent(command, request, reply, connection_generation=1)
    if stage in {"native-accepted", "terminal"}:
        store.native_accepted(command, native_ref="private-native-correlation")
    if stage == "terminal":
        store.terminal(command, text="completed before reboot")
    store.advance_epoch(node_epoch="boot-2", gateway_owner_epoch="gateway-1")
    rebooted = store_at(root, node_epoch="boot-2")
    assert rebooted.get(command).state == stage
    assert rebooted.receipts_after()[-1].identity.node_epoch == "boot-1"
    assert rebooted.native_reference(command) == (
        "private-native-correlation" if stage in {"native-accepted", "terminal"} else None
    )
    if stage == "terminal":
        assert rebooted.output(command) == "completed before reboot"
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        rebooted.effect_intent(command, request, reply, connection_generation=1)


def test_receipt_and_outbox_mutations_rollback_together_on_persistence_error(tmp_path, monkeypatch):
    store = store_at(tmp_path / "node")
    command = identity()
    store.prepare(command, b"payload")
    request, reply = authorization(command)
    original = store._append

    def fail_after_append(db, identity, state, output_digest=None):
        original(db, identity, state, output_digest)
        raise sqlite3.OperationalError("simulated disk failure before commit")

    monkeypatch.setattr(store, "_append", fail_after_append)
    with pytest.raises(AudiaGenticError, match="IO-AGND-001"):
        store.effect_intent(command, request, reply, connection_generation=1)
    assert store.get(command).state == "prepared"
    assert store.authorization_id(command) is None
    assert [r.state for r in store.receipts_after()] == ["prepared"]
    with store._transaction() as db:
        assert db.execute("PRAGMA synchronous").fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE outbox SET state='terminal'")


@pytest.mark.parametrize(
    "field,value", [("cursor", True), ("cursor", -1), ("limit", True), ("limit", 1001)]
)
def test_outbox_bounds(tmp_path, field, value):
    store = store_at(tmp_path / "node")
    with pytest.raises(AudiaGenticError, match="VAL-AGND-001"):
        store.receipts_after(
            value if field == "cursor" else 0, limit=value if field == "limit" else 100
        )


def test_wrong_node_and_future_store_version_fail_closed(tmp_path):
    root = tmp_path / "node"
    store = store_at(root)
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        store_at(root, node_id="other-node")
    with sqlite3.connect(store.path) as db:
        db.execute("PRAGMA user_version=4")
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        store_at(root)


@pytest.mark.parametrize("stage", ["effect-intent", "native-accepted", "terminal"])
def test_exact_authorization_persists_on_reopen_and_never_authorizes_second_effect(tmp_path, stage):
    root = tmp_path / "node"
    store = store_at(root)
    command = advance(store)
    if stage in {"native-accepted", "terminal"}:
        store.native_accepted(command, native_ref="private")
    if stage == "terminal":
        store.terminal(command, text="answer")
    reopened = store_at(root)
    assert reopened.authorization_id(command) == "grant-1"
    request, reply = authorization(command)
    before = reopened.receipts_after()
    assert not reopened.effect_intent(command, request, reply, connection_generation=1)
    # A fresh authorization-request ID using the same grant still cannot Send twice.
    fresh_request = replace(request, message_id="auth-2")
    fresh_reply = replace(
        reply, payload=dict(reply.payload) | {"authorization-request-id": "auth-2"}
    )
    assert not reopened.effect_intent(command, fresh_request, fresh_reply, connection_generation=1)
    changed = replace(reply, payload=dict(reply.payload) | {"authorization-id": "grant-2"})
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        reopened.effect_intent(command, request, changed, connection_generation=1)
    assert reopened.authorization_id(command) == "grant-1"
    assert reopened.receipts_after() == before
    assert "grant-1" not in json.dumps([r.public_payload() for r in before])
    with sqlite3.connect(reopened.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert db.execute("SELECT state,authorization_id FROM commands").fetchone() == (
            stage,
            "grant-1",
        )
    reopened.advance_epoch(node_epoch="boot-2", gateway_owner_epoch="gateway-2")
    historical = store_at(root, node_epoch="boot-2", gateway_owner_epoch="gateway-2")
    assert historical.authorization_id(command) == "grant-1"
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        historical.effect_intent(command, request, reply, connection_generation=1)


@pytest.mark.parametrize("mutation", ["missing", "malformed", "connection", "request", "denied"])
def test_invalid_authorization_never_persists_grant_or_intent(tmp_path, mutation):
    store = store_at(tmp_path / "node")
    command = identity()
    store.prepare(command, b"payload")
    request, reply = authorization(command)
    payload = dict(reply.payload)
    generation = 1
    if mutation == "missing":
        del payload["authorization-id"]
    elif mutation == "malformed":
        payload["authorization-id"] = "../grant"
    elif mutation == "connection":
        generation = 2
    elif mutation == "request":
        payload["authorization-request-id"] = "other-request"
    else:
        payload["authorized"] = False
    with pytest.raises(AudiaGenticError):
        store.effect_intent(
            command, request, replace(reply, payload=payload), connection_generation=generation
        )
    assert store.authorization_id(command) is None
    assert store.get(command).state == "prepared"
    assert len(store.receipts_after()) == 1


@pytest.mark.parametrize("version", [0, 1])
def test_pre_authorization_schema_is_rejected_without_backfill_or_migration(tmp_path, version):
    root = tmp_path / "node"
    root.mkdir(mode=0o700)
    path = root / "receipts.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE commands (command TEXT PRIMARY KEY, state TEXT)")
        db.execute("INSERT INTO commands VALUES ('legacy-command','effect-intent')")
        db.execute(f"PRAGMA user_version={version}")
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        store_at(root)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == version
        assert db.execute("SELECT * FROM commands").fetchall() == [
            ("legacy-command", "effect-intent")
        ]
        assert "authorization_id" not in {r[1] for r in db.execute("PRAGMA table_info(commands)")}


def test_concurrent_distinct_grants_pin_only_winning_authorization(tmp_path):
    root = tmp_path / "node"
    stores = [store_at(root), store_at(root)]
    command = identity()
    stores[0].prepare(command, b"payload")
    request, reply = authorization(command)

    def contend(index):
        grant = f"grant-{index + 1}"
        changed = replace(reply, payload=dict(reply.payload) | {"authorization-id": grant})
        try:
            return grant, stores[index].effect_intent(
                command, request, changed, connection_generation=1
            )
        except AudiaGenticError as error:
            assert error.code == "CON-AGND-001"
            return grant, False

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(contend, range(2)))
    winners = [grant for grant, won in results if won]
    assert len(winners) == 1
    reopened = store_at(root)
    assert reopened.authorization_id(command) == winners[0]
    assert [r.state for r in reopened.receipts_after()] == ["prepared", "effect-intent"]


# Local ACK API tests. Authentication/current-channel facts are injected by the
# trusted owner, never reconstructed from incoming ACK fields.
def live_connection(**changes):
    from audiagentic.components.agents.gateway.node.authority import NodeConnectionIdentity

    return NodeConnectionIdentity(
        **(
            dict(
                node_id="node-1",
                node_epoch="boot-1",
                gateway_owner_epoch="gateway-1",
                connection_generation=1,
            )
            | changes
        )
    )


def ack_frame(store, receipt, **payload_changes):
    from audiagentic.components.agents.gateway.node.contracts import Frame

    return Frame(
        1,
        "reconcile-result",
        "ack-1",
        "node-1",
        "boot-1",
        "gateway-1",
        1,
        {
            "kind": "receipt-ack",
            "server-id": "server-1",
            "log-incarnation-id": store.log_incarnation_id,
            "connection-generation": 1,
            "through-sequence": receipt.sequence,
            "through-receipt-sha256": receipt.digest,
            **payload_changes,
        },
    )


def accept_ack(store, frame, **trusted_changes):
    return store.acknowledge(
        frame,
        **(
            dict(expected_server_id="server-1", current_connection=live_connection())
            | trusted_changes
        ),
    )


def v2_fixture(root):
    """Create the exact old v2 shape with real command/outbox evidence."""
    store = store_at(root)
    command = advance(store)
    store.native_accepted(command, native_ref="private-native-ref")
    store.terminal(command, text="private-output")
    store.prepare(identity(command_id="other-command", request_id="other-request"), b"payload")
    with sqlite3.connect(store.path) as db:
        db.execute("DROP TABLE receipt_checkpoint")
        db.execute("ALTER TABLE owner RENAME TO owner_v3")
        db.execute(
            "CREATE TABLE owner (singleton INTEGER PRIMARY KEY CHECK(singleton=1), node TEXT NOT NULL, epoch TEXT NOT NULL, gateway TEXT NOT NULL)"
        )
        db.execute("INSERT INTO owner SELECT singleton,node,epoch,gateway FROM owner_v3")
        db.execute("DROP TABLE owner_v3")
        db.execute("PRAGMA user_version=2")
    return store.path


def durable_facts(path):
    with sqlite3.connect(path) as db:
        return (
            db.execute("SELECT * FROM commands ORDER BY command").fetchall(),
            db.execute("SELECT * FROM outbox ORDER BY sequence").fetchall(),
            db.execute("SELECT * FROM sqlite_sequence ORDER BY name").fetchall(),
        )


def test_v2_guarded_migration_preserves_every_receipt_and_authorization_fact(tmp_path):
    root = tmp_path / "node"
    path = v2_fixture(root)
    before = durable_facts(path)
    migrated = store_at(root)
    assert durable_facts(path) == before
    assert migrated.authorization_id(identity()) == "grant-1"
    assert migrated.native_reference(identity()) == "private-native-ref"
    assert migrated.output(identity()) == "private-output"
    checkpoint = migrated.ack_checkpoint()
    assert checkpoint.server_id is None and checkpoint.through_sequence == 0
    assert checkpoint.through_receipt_sha256 is None
    import uuid

    assert uuid.UUID(checkpoint.log_incarnation_id).version == 4
    assert store_at(root).log_incarnation_id == checkpoint.log_incarnation_id
    next_receipt = migrated.prepare(identity(command_id="after-migration"), b"payload")
    assert next_receipt.sequence == 6
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3


def test_migration_failure_rolls_back_schema_uuid_and_cursor(tmp_path, monkeypatch):
    root = tmp_path / "node"
    path = v2_fixture(root)
    before = durable_facts(path)
    original = NodeReceiptStore._create_checkpoint

    def fail_after_create(db):
        original(db)
        raise sqlite3.OperationalError("failed migration commit")

    monkeypatch.setattr(NodeReceiptStore, "_create_checkpoint", staticmethod(fail_after_create))
    with pytest.raises(AudiaGenticError, match="IO-AGND-001"):
        store_at(root)
    assert durable_facts(path) == before
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert "log_incarnation_id" not in {r[1] for r in db.execute("PRAGMA table_info(owner)")}
        assert not db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='receipt_checkpoint'"
        ).fetchone()


@pytest.mark.parametrize(
    "damage", ["missing-authorization", "missing-trigger", "unexpected-checkpoint"]
)
def test_migration_rejects_incomplete_or_ambiguous_v2(tmp_path, damage):
    root = tmp_path / "node"
    path = v2_fixture(root)
    with sqlite3.connect(path) as db:
        if damage == "missing-authorization":
            db.execute("ALTER TABLE commands RENAME COLUMN authorization_id TO unknown_id")
        elif damage == "missing-trigger":
            db.execute("DROP TRIGGER outbox_no_delete")
        else:
            db.execute("CREATE TABLE receipt_checkpoint (unknown TEXT)")
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        store_at(root)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_log_uuid_and_ack_survive_reopen_and_epoch_rotation_not_database_recreation(tmp_path):
    root = tmp_path / "node"
    store = store_at(root)
    receipt = store.prepare(identity(), b"payload")
    log_id = store.log_incarnation_id
    accepted = accept_ack(store, ack_frame(store, receipt))
    assert store_at(root).ack_checkpoint() == accepted
    store.advance_epoch(node_epoch="boot-2", gateway_owner_epoch="gateway-2")
    current = store_at(root, node_epoch="boot-2", gateway_owner_epoch="gateway-2")
    assert current.log_incarnation_id == log_id
    assert current.ack_checkpoint() == accepted
    # Recreate only the named database; no recursive deletion or artifact purge.
    store.path.unlink()
    recreated = store_at(root)
    assert recreated.log_incarnation_id != log_id
    assert recreated.ack_checkpoint().through_sequence == 0
    assert recreated.ack_checkpoint().server_id is None
    with pytest.raises(AudiaGenticError):
        accept_ack(recreated, ack_frame(store_at(root), receipt, **{"log-incarnation-id": log_id}))


def test_cumulative_ack_duplicate_noop_regression_and_changed_digest_conflict(
    tmp_path, monkeypatch
):
    store = store_at(tmp_path / "node")
    command = advance(store)
    receipts = store.receipts_after()
    # A valid cumulative ACK may cover already emitted intermediate receipts.
    accepted = accept_ack(store, ack_frame(store, receipts[-1]))
    assert accepted.through_sequence == 2 and accepted.server_id == "server-1"

    def no_write(*args):
        pytest.fail("Duplicate ACK mutated the checkpoint")

    monkeypatch.setattr(store, "_write_ack", no_write)
    assert accept_ack(store, ack_frame(store, receipts[-1])) == accepted
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        accept_ack(store, ack_frame(store, receipts[0]))
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        accept_ack(store, ack_frame(store, receipts[-1], **{"through-receipt-sha256": "0" * 64}))
    assert store.ack_checkpoint() == accepted
    assert store.get(command).state == "effect-intent"  # ACK isn't successful work.
    assert store.authorization_id(command) == "grant-1"
    assert store.receipts_after() == receipts  # ACK isn't permission to delete.


@pytest.mark.parametrize(
    "key,value",
    [
        ("kind", "other"),
        ("server-id", "server-2"),
        ("log-incarnation-id", "00000000-0000-4000-8000-000000000000"),
        ("log-incarnation-id", "invalid"),
        ("connection-generation", 2),
        ("connection-generation", True),
        ("through-sequence", True),
        ("through-sequence", 0),
        ("through-sequence", 2),
        ("through-sequence", -1),
        ("through-sequence", 1.0),
        ("through-sequence", 2**63),
        ("through-receipt-sha256", "0" * 64),
        ("through-receipt-sha256", "A" * 64),
        ("through-receipt-sha256", True),
        ("unexpected", "value"),
    ],
)
def test_bad_ack_never_establishes_server_binding_or_cursor(tmp_path, key, value):
    store = store_at(tmp_path / "node")
    receipt = store.prepare(identity(), b"payload")
    before = store.ack_checkpoint()
    with pytest.raises(AudiaGenticError):
        accept_ack(store, ack_frame(store, receipt, **{key: value}))
    assert store.ack_checkpoint() == before
    assert store.receipts_after() == (receipt,)


@pytest.mark.parametrize(
    "key",
    [
        "kind",
        "server-id",
        "log-incarnation-id",
        "connection-generation",
        "through-sequence",
        "through-receipt-sha256",
    ],
)
def test_ack_missing_field_is_rejected(tmp_path, key):
    store = store_at(tmp_path / "node")
    receipt = store.prepare(identity(), b"payload")
    frame = ack_frame(store, receipt)
    payload = dict(frame.payload)
    del payload[key]
    with pytest.raises(AudiaGenticError, match="VAL-AGND-001"):
        accept_ack(store, replace(frame, payload=payload))
    assert store.ack_checkpoint().server_id is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("node_id", "foreign"),
        ("node_epoch", "old"),
        ("gateway_owner_epoch", "old"),
        ("connection_generation", True),
    ],
)
def test_ack_rejects_untrusted_or_stale_connection_facts(tmp_path, field, value):
    store = store_at(tmp_path / "node")
    receipt = store.prepare(identity(), b"payload")
    with pytest.raises(AudiaGenticError):
        accept_ack(
            store, ack_frame(store, receipt), current_connection=live_connection(**{field: value})
        )
    assert store.ack_checkpoint().through_sequence == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("node_id", "foreign"),
        ("node_epoch", "old"),
        ("gateway_owner_epoch", "unbound"),
        ("type", "receipt"),
    ],
)
def test_ack_frame_scope_cannot_override_trusted_context(tmp_path, field, value):
    store = store_at(tmp_path / "node")
    receipt = store.prepare(identity(), b"payload")
    with pytest.raises(AudiaGenticError):
        accept_ack(store, replace(ack_frame(store, receipt), **{field: value}))
    assert store.ack_checkpoint().server_id is None


def test_ack_singleton_server_binding_blocks_retarget_even_with_new_trusted_argument(tmp_path):
    store = store_at(tmp_path / "node")
    receipt = store.prepare(identity(), b"payload")
    accepted = accept_ack(store, ack_frame(store, receipt))
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        accept_ack(
            store,
            ack_frame(store, receipt, **{"server-id": "server-2"}),
            expected_server_id="server-2",
        )
    assert store_at(store.root).ack_checkpoint() == accepted


def test_current_epoch_ack_can_cover_historical_receipt_without_reauthorizing_it(tmp_path):
    store = store_at(tmp_path / "node")
    receipt = store.prepare(identity(), b"payload")
    old_frame = ack_frame(store, receipt)
    store.advance_epoch(node_epoch="boot-2", gateway_owner_epoch="gateway-2")
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        accept_ack(store, old_frame)
    current = store_at(store.root, node_epoch="boot-2", gateway_owner_epoch="gateway-2")
    frame = replace(
        ack_frame(current, receipt, **{"connection-generation": 3}),
        node_epoch="boot-2",
        gateway_owner_epoch="gateway-2",
    )
    accepted = accept_ack(
        current,
        frame,
        current_connection=live_connection(
            node_epoch="boot-2", gateway_owner_epoch="gateway-2", connection_generation=3
        ),
    )
    assert accepted.through_sequence == receipt.sequence
    with pytest.raises(AudiaGenticError):
        current.prepare(identity(), b"payload")


def test_ack_transaction_failure_preserves_unbound_cursor(tmp_path, monkeypatch):
    store = store_at(tmp_path / "node")
    receipt = store.prepare(identity(), b"payload")
    original = store._write_ack

    def fail_after_update(*args):
        original(*args)
        raise sqlite3.OperationalError("simulated ACK failure")

    monkeypatch.setattr(store, "_write_ack", fail_after_update)
    with pytest.raises(AudiaGenticError, match="IO-AGND-001"):
        accept_ack(store, ack_frame(store, receipt))
    assert store.ack_checkpoint().server_id is None
    assert store.ack_checkpoint().through_sequence == 0


def test_public_receipt_digest_remains_stable_without_log_or_private_fields(tmp_path):
    from audiagentic.components.agents.gateway.node.contracts import canonical_json

    store = store_at(tmp_path / "node")
    receipt = store.prepare(identity(), b"payload")
    original = receipt.public_payload()
    assert receipt.digest == hashlib.sha256(canonical_json(original)).hexdigest()
    accept_ack(store, ack_frame(store, receipt))
    assert store.receipts_after()[0].public_payload() == original
    assert "log-incarnation-id" not in original and "server-id" not in original


_ACK_CHILD = r"""
import json,sys,time
from pathlib import Path
from audiagentic.components.agents.gateway.node.receipts import NodeReceiptStore
from audiagentic.components.agents.gateway.node.contracts import Frame
from audiagentic.components.agents.gateway.node.authority import NodeConnectionIdentity
settings=json.loads(sys.stdin.readline())
root=Path(settings['root'])
def pause():
    (root/'ack-ready').write_text('ready')
    while True: time.sleep(1)
if settings['stage']=='migration':
    original=NodeReceiptStore._create_checkpoint
    def held(db):
        original(db)
        pause()
    NodeReceiptStore._create_checkpoint=staticmethod(held)
s=NodeReceiptStore(root=root,node_id='node-1',node_epoch='boot-1',gateway_owner_epoch='gateway-1')
if settings['stage']=='ack-before-commit':
    original=s._write_ack
    def held(*args):
        original(*args)
        pause()
    s._write_ack=held
s.acknowledge(Frame.from_bytes(settings['ack'].encode()),expected_server_id='server-1',
    current_connection=NodeConnectionIdentity('node-1','boot-1','gateway-1',1))
pause()
"""


def kill_at_ack_barrier(root, stage, frame=None):
    child = subprocess.Popen(
        [sys.executable, "-c", _ACK_CHILD],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=child_environment(),
    )
    try:
        child.stdin.write(
            json.dumps(
                {
                    "root": str(root),
                    "stage": stage,
                    "ack": frame.to_bytes().decode() if frame is not None else "",
                }
            )
            + "\n"
        )
        child.stdin.flush()
        deadline = time.monotonic() + 10
        while (
            not (root / "ack-ready").exists()
            and child.poll() is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        if not (root / "ack-ready").exists():
            child.kill()
            _, error = child.communicate(timeout=5)
            pytest.fail("ACK child missed persistence barrier: " + error)
        child.kill()
        child.communicate(timeout=5)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)


@pytest.mark.parametrize("stage,sequence", [("ack-before-commit", 0), ("ack-after-commit", 1)])
def test_hard_kill_ack_reopen_is_atomic_and_does_not_delete_receipts(tmp_path, stage, sequence):
    root = tmp_path / "node"
    store = store_at(root)
    receipt = store.prepare(identity(), b"payload")
    log_id = store.log_incarnation_id
    before = durable_facts(store.path)
    frame = ack_frame(store, receipt)
    kill_at_ack_barrier(root, stage, frame)
    reopened = store_at(root)
    checkpoint = reopened.ack_checkpoint()
    assert checkpoint.log_incarnation_id == log_id
    assert checkpoint.through_sequence == sequence
    assert checkpoint.server_id == ("server-1" if sequence else None)
    assert durable_facts(reopened.path) == before
    accepted = accept_ack(reopened, frame)
    assert accepted.through_sequence == 1
    assert reopened.receipts_after() == (receipt,)


def test_hard_kill_v2_migration_leaves_complete_old_schema_then_retries_safely(tmp_path):
    root = tmp_path / "node"
    path = v2_fixture(root)
    before = durable_facts(path)
    kill_at_ack_barrier(root, "migration")
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert "log_incarnation_id" not in {r[1] for r in db.execute("PRAGMA table_info(owner)")}
        assert not db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='receipt_checkpoint'"
        ).fetchone()
    assert durable_facts(path) == before
    reopened = store_at(root)
    assert reopened.ack_checkpoint().through_sequence == 0
    assert durable_facts(path) == before
    assert store_at(root).log_incarnation_id == reopened.log_incarnation_id


@pytest.mark.parametrize("damage", ["missing-row", "missing-log", "unknown-row", "changed-digest"])
def test_v3_missing_or_corrupt_checkpoint_never_resets_itself(tmp_path, damage):
    root = tmp_path / "node"
    store = store_at(root)
    receipt = store.prepare(identity(), b"payload")
    accept_ack(store, ack_frame(store, receipt))
    with sqlite3.connect(store.path) as db:
        if damage == "missing-row":
            db.execute("DELETE FROM receipt_checkpoint")
        elif damage == "missing-log":
            db.execute("UPDATE owner SET log_incarnation_id=NULL")
        elif damage == "unknown-row":
            db.execute("UPDATE receipt_checkpoint SET through_sequence=99")
        else:
            db.execute("UPDATE receipt_checkpoint SET through_digest=?", ("0" * 64,))
    with pytest.raises(AudiaGenticError):
        store_at(root)
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        if damage == "missing-row":
            assert not db.execute("SELECT 1 FROM receipt_checkpoint").fetchone()


def test_ack_cannot_take_connection_facts_from_payload(tmp_path):
    store = store_at(tmp_path / "node")
    receipt = store.prepare(identity(), b"payload")
    frame = ack_frame(store, receipt)
    with pytest.raises(AudiaGenticError, match="VAL-AGND-001"):
        accept_ack(store, frame, current_connection=dict(frame.payload))
    assert store.ack_checkpoint().server_id is None
