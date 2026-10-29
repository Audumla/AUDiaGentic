"""Private node effect receipts, not canonical gateway Work or a native executor.

WAL + synchronous=FULL commits receipt state and its append-only outbox together,
under one Foundation AdvisoryLock. Never hold that lock over network/native I/O.
Only a newly committed effect-intent returns True; a duplicate never grants a
second native call. A crash/commit error after intent is uncertain, never unsent.
Old epochs are evidence-only. Epoch rotation is an explicit owner CAS operation.
One schema (SCHEMA_VERSION): one durable log incarnation, a server-bound cumulative
ACK cursor and a private artifact_kind that durably distinguishes worker envelopes
from native plaintext (no JSON guessing). Stores of any other version are rejected,
never migrated: earlier numbers were unreleased prototypes.
ACK is receipt custody, never native success, work completion or permission to
delete evidence. Current channel/server facts must come from the trusted owner.

Deploy on a protected local filesystem with working SQLite locks/fsync; network
filesystems and cloud-sync folders are unsupported. POSIX directories are private;
Windows ACLs are the deployment owner's responsibility. FULL relies on the OS,
filesystem and drive honoring sync. Process-kill tests are not power-loss proof.
Foundation atomic output fsyncs file content before rename; POSIX additionally
syncs the output directory here. Windows directory-entry power-loss durability
requires deployment qualification. Missing/corrupt artifacts fail closed on read.
Artifact descriptors use leaf no-follow/nonblocking flags where available and
pre/post redirect checks. Protected owner storage remains required: these checks
are not a universal descriptor-relative filesystem sandbox, particularly on Windows.
No distributed exactly-once or portable hardware power-loss guarantee is claimed.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.digest import is_sha256_hex
from audiagentic.foundation.io import atomic_write_bytes
from audiagentic.foundation.paths.home import global_service_runtime
from audiagentic.foundation.system.advisory_lock import AdvisoryLock

from .contracts import (
    MAX_FRAME_BYTES,
    CommandIdentity,
    Frame,
    _constant,
    _identifier,
    _integer,
    _pairs,
    canonical_json,
    conflict,
    invalid,
    validate_effect_authorization,
)
from .prepared_evidence import check_private_evidence_path

io_error = make_error_factory("IO", "AGND", "agents-node")

# The first released receipt schema. Earlier numbers were development prototypes
# that never shipped, so there is no migration and they are not supported.
SCHEMA_VERSION = 4


@dataclass(frozen=True)
class Receipt:
    identity: CommandIdentity
    state: str
    sequence: int
    output_sha256: str | None = None

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.public_payload())).hexdigest()

    def public_payload(self) -> dict:
        """No native references, local paths, payload bytes or transcript text."""
        return {
            "identity": self.identity.to_mapping(),
            "state": self.state,
            "receipt-sequence": self.sequence,
            "output-sha256": self.output_sha256,
        }


def _log_id(value):
    if not isinstance(value, str):
        raise invalid(1, "Receipt log identity must be a canonical UUID")
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise invalid(1, "Receipt log identity must be a canonical UUID") from None
    if str(parsed) != value or parsed.version != 4:
        raise invalid(1, "Receipt log identity must be a canonical UUID v4")
    return value


def _digest(value):
    if not is_sha256_hex(value):
        raise invalid(1, "Receipt digest must be a lowercase SHA256")
    return value


@dataclass(frozen=True)
class ReceiptCheckpoint:
    log_incarnation_id: str
    server_id: str | None
    through_sequence: int
    through_receipt_sha256: str | None


@dataclass(frozen=True)
class ReceiptOwnerScope:
    node_id: str
    node_epoch: str
    gateway_owner_epoch: str

    def __post_init__(self):
        for value in (self.node_id, self.node_epoch, self.gateway_owner_epoch):
            _identifier(value)


class NodeReceiptStore:
    @classmethod
    def read_owner_scope(cls, root: Path, *, expected_node_id: str) -> ReceiptOwnerScope | None:
        """Read actual persisted ownership for restart, without creating/migrating.

        Caller must already hold exclusive node lifecycle ownership and serialize
        receipt writers. None means no database exists. Invalid/unsupported evidence is
        never interpreted as a fresh store. Lifecycle exclusivity belongs to the
        caller's managed node process, not this short receipt-file read fence.
        """
        _identifier(expected_node_id)
        if not isinstance(root, Path) or not root.is_absolute():
            raise invalid(1, "Node receipt root must be an absolute owner-local path")
        path, lock = root / "receipts.sqlite3", root / "receipts.lock"
        wal, shm = root / "receipts.sqlite3-wal", root / "receipts.sqlite3-shm"
        if any(
            part.is_symlink() or getattr(part, "is_junction", lambda: False)()
            for part in (root, *root.parents, path, lock, wal, shm)
        ):
            raise invalid(1, "Node receipt paths must not be symlinks or junctions")
        if not path.exists():
            return None
        try:
            # SQLite owns the read snapshot; no lifecycle claim, lock-file creation,
            # initialization, journal-mode mutation or migration on this path.
            # Without a WAL, immutable avoids SQLite recreating WAL/SHM on a
            # checkpointed WAL-mode database. This requires caller exclusivity.
            # With live WAL evidence, never ignore it or create a missing index.
            if wal.exists() and not shm.exists():
                raise conflict(1, "Receipt WAL requires its existing shared-memory index")
            uri = path.as_uri() + ("?mode=ro" if wal.exists() else "?mode=ro&immutable=1")
            db = sqlite3.connect(uri, uri=True, isolation_level=None)
            try:
                db.execute("BEGIN")
                if db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                    raise conflict(1, "Unsupported persisted node receipt schema")
                cls._validate_schema(db)
                if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise conflict(1, "Persisted node receipt integrity check failed")
                cls._checkpoint(db)
                rows = db.execute("SELECT singleton,node,epoch,gateway FROM owner").fetchall()
                if len(rows) != 1 or rows[0][0:2] != (1, expected_node_id):
                    raise conflict(1, "Persisted receipt owner is missing or belongs to another node")
                return ReceiptOwnerScope(*rows[0][1:])
            finally:
                db.close()
        except (sqlite3.Error, OSError):
            raise io_error(1, "Cannot read persisted node receipt owner scope") from None

    def __init__(
        self, *, node_id: str, node_epoch: str, gateway_owner_epoch: str, root: Path | None = None
    ):
        self.node_id = _identifier(node_id)
        self.node_epoch = _identifier(node_epoch)
        self.gateway_owner_epoch = _identifier(gateway_owner_epoch)
        root = root if root is not None else global_service_runtime() / "execution-nodes" / node_id
        if not isinstance(root, Path) or not root.is_absolute():
            raise invalid(1, "Node receipt root must be an absolute owner-local path")
        self.root = root
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            if os.name == "posix" and self.root.stat().st_mode & 0o077:
                raise invalid(1, "Node receipt root must exclude group and other access")
            self.path = self.root / "receipts.sqlite3"
            self.lock_path = self.root / "receipts.lock"
            self.outputs = self.root / "outputs"
            if self.path.is_symlink() or self.lock_path.is_symlink() or self.outputs.is_symlink():
                raise invalid(1, "Node receipt files must not be symlinks")
            with self._transaction() as db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, SCHEMA_VERSION):
                    raise conflict(1, "Unsupported node receipt schema version")
                if version == 0:
                    if db.execute(
                        "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
                    ).fetchone():
                        raise conflict(1, "Unversioned existing node receipt store is unsupported")
                    self._create_schema(db)
                    db.execute("INSERT INTO owner VALUES (1,?,?,?,?)", (*self._scope, str(uuid.uuid4())))
                    db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                else:
                    self._validate_schema(db)
                if db.execute("SELECT node FROM owner WHERE singleton=1").fetchone() != (node_id,):
                    raise conflict(1, "Receipt store belongs to another node")
                # A store missing its log identity is corruption, never a new log.
                self._checkpoint(db)
        except OSError:
            raise io_error(1, "Cannot initialize private node receipt storage") from None

    @staticmethod
    def _create_schema(db):
        db.execute(
            "CREATE TABLE owner (singleton INTEGER PRIMARY KEY CHECK(singleton=1), node TEXT NOT NULL, epoch TEXT NOT NULL, gateway TEXT NOT NULL, log_incarnation_id TEXT)"
        )
        db.execute(
            "CREATE TABLE commands (command TEXT PRIMARY KEY, identity TEXT NOT NULL, payload BLOB NOT NULL, state TEXT NOT NULL CHECK(state IN ('prepared','effect-intent','native-accepted','terminal')), native_ref TEXT, output_digest TEXT, sequence INTEGER NOT NULL, authorization_id TEXT, artifact_kind TEXT)"
        )
        db.execute(
            "CREATE TABLE outbox (sequence INTEGER PRIMARY KEY AUTOINCREMENT, command TEXT NOT NULL REFERENCES commands(command), state TEXT NOT NULL, output_digest TEXT)"
        )
        db.execute(
            "CREATE TRIGGER outbox_no_update BEFORE UPDATE ON outbox BEGIN SELECT RAISE(ABORT, 'append-only outbox'); END"
        )
        db.execute(
            "CREATE TRIGGER outbox_no_delete BEFORE DELETE ON outbox BEGIN SELECT RAISE(ABORT, 'append-only outbox'); END"
        )
        db.execute(
            "CREATE TABLE receipt_checkpoint (singleton INTEGER PRIMARY KEY CHECK(singleton=1), server_id TEXT, through_sequence INTEGER NOT NULL, through_digest TEXT)"
        )
        db.execute("INSERT INTO receipt_checkpoint VALUES (1,NULL,0,NULL)")

    @staticmethod
    def _validate_schema(db):
        expected = {
            "owner": {"singleton", "node", "epoch", "gateway", "log_incarnation_id"},
            "commands": {
                "command",
                "identity",
                "payload",
                "state",
                "native_ref",
                "output_digest",
                "sequence",
                "authorization_id",
                "artifact_kind",
            },
            "outbox": {"sequence", "command", "state", "output_digest"},
        }
        for table, columns in expected.items():
            if {row[1] for row in db.execute(f"PRAGMA table_info({table})")} != columns:
                raise conflict(1, "Unsupported node receipt schema shape")
        triggers = {
            row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        }
        if not {"outbox_no_update", "outbox_no_delete"} <= triggers:
            raise conflict(1, "Node receipt append-only guards are missing")

    @staticmethod
    def _checkpoint(db):
        if {row[1] for row in db.execute("PRAGMA table_info(receipt_checkpoint)")} != {
            "singleton",
            "server_id",
            "through_sequence",
            "through_digest",
        }:
            raise conflict(1, "Node receipt checkpoint schema is missing or invalid")
        incarnations = db.execute(
            "SELECT log_incarnation_id FROM owner WHERE singleton=1"
        ).fetchall()
        if len(incarnations) != 1:
            raise conflict(1, "Node receipt log incarnation is missing")
        log_id = _log_id(incarnations[0][0])
        rows = db.execute(
            "SELECT server_id,through_sequence,through_digest FROM receipt_checkpoint"
        ).fetchall()
        if len(rows) != 1:
            raise conflict(1, "Node receipt log identity is missing or ambiguous")
        server_id, sequence, digest = rows[0]
        _integer(sequence, 0)
        if (sequence == 0 and (digest is not None or server_id is not None)) or (
            sequence > 0 and (server_id is None or digest is None)
        ):
            raise conflict(1, "Invalid node receipt checkpoint state")
        if server_id is not None:
            _identifier(server_id)
            _digest(digest)
            if NodeReceiptStore._outbox_receipt(db, sequence).digest != digest:
                raise conflict(1, "Stored ACK checkpoint does not match local receipt evidence")
        return ReceiptCheckpoint(log_id, server_id, sequence, digest)

    @staticmethod
    def _outbox_receipt(db, sequence):
        row = db.execute(
            "SELECT c.identity,o.state,o.sequence,o.output_digest FROM outbox o JOIN commands c ON c.command=o.command WHERE o.sequence=?",
            (sequence,),
        ).fetchone()
        if row is None:
            raise conflict(1, "Receipt ACK references an absent local outbox row")
        return Receipt(CommandIdentity.from_mapping(json.loads(row[0])), row[1], row[2], row[3])

    @property
    def _scope(self):
        return self.node_id, self.node_epoch, self.gateway_owner_epoch

    @contextmanager
    def _transaction(self):
        try:
            with AdvisoryLock(self.lock_path):
                db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
                try:
                    if db.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                        raise io_error(1, "Node receipt storage requires WAL support")
                    db.execute("PRAGMA synchronous=FULL")
                    db.execute("PRAGMA foreign_keys=ON")
                    if db.execute("PRAGMA synchronous").fetchone()[0] != 2:
                        raise io_error(1, "Node receipt storage requires synchronous FULL")
                    db.execute("BEGIN IMMEDIATE")
                    try:
                        yield db
                        db.execute("COMMIT")
                    except BaseException:
                        if db.in_transaction:
                            db.execute("ROLLBACK")
                        raise
                finally:
                    db.close()
        except (sqlite3.Error, OSError, ValueError, UnicodeError):
            raise io_error(
                1, "Node receipt persistence failed; effect outcome must be reconciled"
            ) from None

    def _require_current(self, db, identity: CommandIdentity | None = None):
        scope = db.execute("SELECT node,epoch,gateway FROM owner WHERE singleton=1").fetchone()
        if scope != self._scope or (
            identity is not None
            and (identity.node_id, identity.node_epoch, identity.gateway_owner_epoch) != self._scope
        ):
            raise conflict(1, "Stale node or gateway epoch is evidence-only")

    def advance_epoch(self, *, node_epoch: str, gateway_owner_epoch: str) -> None:
        """Owner-only epoch handoff; stale store instances cannot mutate afterward."""
        _identifier(node_epoch)
        _identifier(gateway_owner_epoch)
        with self._transaction() as db:
            self._require_current(db)
            if node_epoch == self.node_epoch and gateway_owner_epoch == self.gateway_owner_epoch:
                raise conflict(1, "Epoch handoff must change an epoch")
            db.execute(
                "UPDATE owner SET epoch=?, gateway=? WHERE singleton=1",
                (node_epoch, gateway_owner_epoch),
            )

    @staticmethod
    def _row(db, identity):
        row = db.execute(
            "SELECT identity,state,sequence,output_digest,native_ref,authorization_id,artifact_kind FROM commands WHERE command=?",
            (identity.command_id,),
        ).fetchone()
        if row is None:
            raise conflict(1, "Command has not been prepared")
        if row[0] != canonical_json(identity.to_mapping()).decode():
            raise conflict(1, "Command identity or payload digest changed")
        return row

    @staticmethod
    def _append(db, identity, state, output_digest=None):
        cursor = db.execute(
            "INSERT INTO outbox(command,state,output_digest) VALUES (?,?,?)",
            (identity.command_id, state, output_digest),
        )
        sequence = cursor.lastrowid
        db.execute(
            "UPDATE commands SET state=?,sequence=?,output_digest=? WHERE command=?",
            (state, sequence, output_digest, identity.command_id),
        )
        return Receipt(identity, state, sequence, output_digest)

    def _receipt(self, identity, row):
        if row[1] == "terminal":
            self._read_output(row[3])
        return Receipt(identity, row[1], row[2], row[3])

    def prepare(self, identity: CommandIdentity, payload: bytes) -> Receipt:
        if not isinstance(payload, bytes) or len(payload) > MAX_FRAME_BYTES:
            raise invalid(1, "Command payload must be bounded bytes")
        if hashlib.sha256(payload).hexdigest() != identity.payload_sha256:
            raise conflict(1, "Command payload does not match its authorized digest")
        with self._transaction() as db:
            self._require_current(db, identity)
            existing = db.execute(
                "SELECT 1 FROM commands WHERE command=?", (identity.command_id,)
            ).fetchone()
            if existing:
                row = self._row(db, identity)
                stored = db.execute(
                    "SELECT payload FROM commands WHERE command=?", (identity.command_id,)
                ).fetchone()[0]
                if stored != payload:
                    raise conflict(1, "Command payload changed")
                return self._receipt(identity, row)
            db.execute(
                "INSERT INTO commands(command,identity,payload,state,sequence) VALUES (?,?,?,'prepared',0)",
                (identity.command_id, canonical_json(identity.to_mapping()).decode(), payload),
            )
            return self._append(db, identity, "prepared")

    def effect_intent(
        self, identity: CommandIdentity, request: Frame, reply: Frame, *, connection_generation: int
    ) -> bool:
        """True once only, after durable intent. Never invokes native/provider code."""
        authorization_id = validate_effect_authorization(
            identity, request, reply, connection_generation=connection_generation
        )
        with self._transaction() as db:
            self._require_current(db, identity)
            row = self._row(db, identity)
            if row[1] != "prepared":
                if row[5] != authorization_id:
                    raise conflict(1, "Command authorization identity changed")
                return False
            if row[5] is not None and row[5] != authorization_id:
                raise conflict(1, "Command authorization identity changed")
            db.execute(
                "UPDATE commands SET authorization_id=? WHERE command=?",
                (authorization_id, identity.command_id),
            )
            self._append(db, identity, "effect-intent")
            return True

    def native_accepted(self, identity: CommandIdentity, *, native_ref: str) -> Receipt:
        if not isinstance(native_ref, str) or not native_ref or len(native_ref) > 4096:
            raise invalid(1, "Native acceptance requires a bounded private reference")
        try:
            native_ref.encode("utf-8")
        except UnicodeError:
            raise invalid(1, "Native reference must be valid UTF-8") from None
        with self._transaction() as db:
            self._require_current(db, identity)
            row = self._row(db, identity)
            if row[1] in {"native-accepted", "terminal"}:
                if row[4] != native_ref:
                    raise conflict(1, "Native receipt changed")
                return self._receipt(identity, row)
            if row[1] != "effect-intent":
                raise conflict(1, "Native acceptance requires committed effect intent")
            db.execute(
                "UPDATE commands SET native_ref=? WHERE command=?",
                (native_ref, identity.command_id),
            )
            return self._append(db, identity, "native-accepted")

    def terminal(self, identity: CommandIdentity, *, text: str) -> Receipt:
        try:
            raw = text.encode("utf-8")
        except (AttributeError, UnicodeError):
            raise invalid(1, "Terminal output must be UTF-8 text") from None
        digest = hashlib.sha256(raw).hexdigest()
        with self._transaction() as db:
            self._require_current(db, identity)
            row = self._row(db, identity)
            if row[1] == "terminal":
                if row[6] == "worker-terminal-result":
                    raise conflict(1, "Worker terminal cannot be consumed as native plaintext")
                if row[3] != digest:
                    raise conflict(1, "Terminal output changed")
                self._read_output(digest)
                return self._receipt(identity, row)
            if row[1] != "native-accepted":
                raise conflict(1, "Terminal observation requires native acceptance evidence")
            self._persist_output(raw, digest)
            db.execute(
                "UPDATE commands SET artifact_kind='native-plaintext' WHERE command=?",
                (identity.command_id,),
            )
            return self._append(db, identity, "terminal", digest)

    def terminal_from_worker_result(
        self, identity: CommandIdentity, *, preparation, proof
    ) -> Receipt:
        """Commit locally verified worker success directly from authorized intent.

        No native-accepted receipt or native reference is invented. WorkerError,
        invalid/missing proof and cleanup exceptions cannot clear delivery uncertainty.
        Schema v4 stores a private artifact-kind discriminator; historical v3
        rows remain unknown. Public receipt and historical output digests do not
        change. The proof alone does not establish readiness. This adds the
        durable terminal barrier; the producer owner must also fence old writers
        and admit only qualifying one-shot adapters. Universal descendant absence
        is not asserted or required here, and cleanup_proven=False stays honest.
        """
        from .terminal_output import build_worker_terminal_output, parse_worker_terminal_output

        with self._transaction() as db:
            self._require_current(db, identity)
            row = self._row(db, identity)
            if row[1] not in {"effect-intent", "terminal"} or not row[5] or row[4] is not None:
                raise conflict(
                    1,
                    "Worker terminal requires original authorized effect intent without native acceptance",
                )
            if (row[1] == "terminal" and row[6] != "worker-terminal-result") or (
                row[1] == "effect-intent" and row[6] is not None
            ):
                raise conflict(1, "Worker terminal artifact kind is absent or conflicts")
            stored_payload = db.execute(
                "SELECT payload FROM commands WHERE command=?", (identity.command_id,)
            ).fetchone()[0]
            envelope = build_worker_terminal_output(
                identity, preparation=preparation, proof=proof, stored_payload=stored_payload
            )
            raw, digest = envelope.to_bytes(), envelope.digest
            if row[1] == "terminal":
                # A plaintext historical terminal is never upgraded into worker proof.
                existing = self._read_output(row[3]).encode("utf-8")
                parse_worker_terminal_output(
                    existing, expected_identity=identity, expected_sha256=row[3]
                )
                if row[3] != digest or existing != raw:
                    raise conflict(1, "Verified worker terminal output changed")
                return self._receipt(identity, row)
            self._persist_output(raw, digest)
            db.execute(
                "UPDATE commands SET artifact_kind='worker-terminal-result' WHERE command=?",
                (identity.command_id,),
            )
            return self._append(db, identity, "terminal", digest)

    def artifact_kind(self, identity: CommandIdentity) -> str | None:
        """Private artifact descriptor. Null historical kinds are never inferred."""
        with self._transaction() as db:
            return self._row(db, identity)[6]

    def worker_terminal_output(self, identity: CommandIdentity):
        """Read only a durably worker-typed artifact; publish its text, not wrapper."""
        from .terminal_output import parse_worker_terminal_output

        with self._transaction() as db:
            row = self._row(db, identity)
            if row[1] != "terminal" or row[6] != "worker-terminal-result":
                raise conflict(1, "Terminal artifact is not explicitly worker-typed")
            return parse_worker_terminal_output(
                self._read_output(row[3]).encode("utf-8"),
                expected_identity=identity,
                expected_sha256=row[3],
            )

    def _persist_output(self, raw: bytes, digest: str) -> None:
        self.outputs.mkdir(mode=0o700, exist_ok=True)
        if self.outputs.is_symlink():
            raise conflict(1, "Private output directory changed")
        output = self.outputs / (digest + ".txt")
        if output.exists():
            self._read_output(digest)
        else:
            atomic_write_bytes(output, raw)
        if os.name == "posix":
            fd = os.open(self.outputs, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def _read_output_bytes(self, digest, *, max_bytes: int | None = None):
        if not is_sha256_hex(digest):
            raise conflict(1, "Invalid private output digest")
        path = self.outputs / (digest + ".txt")
        check_private_evidence_path(path)
        before = path.lstat()
        if max_bytes is not None:
            _integer(max_bytes)
        # NOFOLLOW protects the leaf on supporting platforms; NONBLOCK prevents
        # a raced-in FIFO from blocking before fstat can reject its file type.
        # Parent/reparse checks still require protected owner storage, especially
        # on Windows: this is not a universal descriptor-relative sandbox.
        flags = os.O_RDONLY
        for flag in ("O_BINARY", "O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC"):
            flags |= getattr(os, flag, 0)
        descriptor = os.open(path, flags)
        try:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode)
                    or getattr(info, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                    or (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino)):
                raise conflict(1, "Private output descriptor changed or is not regular")
            if max_bytes is not None and info.st_size > max_bytes:
                raise invalid(1, "Private terminal artifact exceeds trusted byte bound")
            check_private_evidence_path(path)
            named = path.lstat()
            if (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino):
                raise conflict(1, "Private output path changed during open")
            handle = os.fdopen(descriptor, "rb")
            descriptor = None  # The file object now owns exactly this descriptor.
            with handle:
                raw = handle.read(info.st_size + 1)
                after = os.fstat(handle.fileno())
                check_private_evidence_path(path)
                named = path.lstat()
                if ((named.st_dev, named.st_ino) != (info.st_dev, info.st_ino)
                        or after.st_size != info.st_size or len(raw) != info.st_size):
                    raise conflict(1, "Private output changed during read")
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if max_bytes is not None and len(raw) > max_bytes:
            raise invalid(1, "Private terminal artifact exceeds trusted byte bound")
        if hashlib.sha256(raw).hexdigest() != digest:
            raise conflict(1, "Private terminal output digest mismatch")
        return raw

    def _read_output(self, digest):
        return self._read_output_bytes(digest).decode("utf-8")

    def artifact_bytes(self, identity: CommandIdentity, *, expected_sha256: str,
                       max_bytes: int) -> tuple[str | None, bytes]:
        """Read descriptor and hash-bound terminal bytes with bounded allocation.

        Unlike get(), this does not first materialize output to validate the
        receipt. The same transaction validates its row and bounded file read.
        """
        _integer(max_bytes)
        _digest(expected_sha256)
        with self._transaction() as db:
            row = self._row(db, identity)
            if row[1] != "terminal" or row[3] != expected_sha256:
                raise conflict(1, "Artifact does not match exact terminal receipt digest")
            return row[6], self._read_output_bytes(row[3], max_bytes=max_bytes)

    def output(self, identity: CommandIdentity) -> str:
        """Local owner read, including old epoch evidence; never a public route."""
        with self._transaction() as db:
            row = self._row(db, identity)
            if row[1] != "terminal":
                raise conflict(1, "Command has no verified terminal output")
            return self._read_output(row[3])

    def get(self, identity: CommandIdentity) -> Receipt:
        with self._transaction() as db:
            row = self._row(db, identity)
            return self._receipt(identity, row)

    def native_reference(self, identity: CommandIdentity) -> str | None:
        """Private owner reconciliation evidence, including historical epochs.

        Never place this value in a Frame or central/public receipt.
        """
        with self._transaction() as db:
            return self._row(db, identity)[4]

    def authorization_id(self, identity: CommandIdentity) -> str | None:
        """Private local reconciliation evidence; omitted from routine receipts.

        Historical epochs may read this fact but cannot authorize another effect.
        """
        with self._transaction() as db:
            return self._row(db, identity)[5]

    def receipts_after(self, sequence: int = 0, *, limit: int = 100) -> tuple[Receipt, ...]:
        """Bounded metadata-only replay, including historical command epochs.

        Durable receipt custody is independent of artifact availability. Output
        bytes/hash remain checked by output/get/artifact_bytes, never this path.
        """
        _integer(sequence, 0)
        _integer(limit)
        if limit > 1000:
            raise invalid(1, "Receipt replay limit exceeds 1000")
        with self._transaction() as db:
            if db.execute("SELECT singleton,node FROM owner").fetchall() != [(1, self.node_id)]:
                raise conflict(1, "Receipt replay belongs to another or missing node owner")
            # Nonpositive corrupted keys would otherwise be hidden by every
            # valid cursor's WHERE clause. This is an indexed, bounded check.
            if db.execute("SELECT 1 FROM outbox WHERE sequence<=0 LIMIT 1").fetchone():
                raise conflict(1, "Invalid receipt replay sequence")
            rows = db.execute(
                "SELECT c.identity,o.state,o.sequence,o.output_digest,o.command,c.command FROM outbox o LEFT JOIN commands c ON c.command=o.command WHERE o.sequence>? ORDER BY o.sequence LIMIT ?",
                (sequence, limit),
            ).fetchall()
            receipts = []
            previous = sequence
            for raw_identity, state, current, digest, outbox_command, stored_command in rows:
                if not isinstance(raw_identity, str) or len(raw_identity) > MAX_FRAME_BYTES:
                    raise conflict(1, "Invalid receipt replay command metadata")
                try:
                    identity = CommandIdentity.from_mapping(json.loads(
                        raw_identity, object_pairs_hook=_pairs, parse_constant=_constant,
                    ))
                except (TypeError, ValueError, RecursionError):
                    raise conflict(1, "Invalid receipt replay command identity") from None
                if (identity.node_id != self.node_id
                        or identity.command_id != outbox_command or outbox_command != stored_command
                        or canonical_json(identity.to_mapping()).decode("utf-8") != raw_identity):
                    raise conflict(1, "Receipt replay command identity or node scope changed")
                _integer(current)
                if current != previous + 1:
                    raise conflict(1, "Receipt replay sequence is not contiguous and ordered")
                if state not in ("prepared", "effect-intent", "native-accepted", "terminal"):
                    raise conflict(1, "Invalid receipt replay stage")
                if state == "terminal":
                    _digest(digest)
                elif digest is not None:
                    raise conflict(1, "Nonterminal receipt replay has an output digest")
                receipts.append(Receipt(identity, state, current, digest))
                previous = current
            return tuple(receipts)

    @property
    def log_incarnation_id(self) -> str:
        return self.ack_checkpoint().log_incarnation_id

    def ack_checkpoint(self) -> ReceiptCheckpoint:
        """Local durable custody checkpoint, readable across historical epochs."""
        with self._transaction() as db:
            return self._checkpoint(db)

    @staticmethod
    def _write_ack(db, server_id, sequence, digest):
        db.execute(
            "UPDATE receipt_checkpoint SET server_id=?,through_sequence=?,through_digest=? WHERE singleton=1",
            (server_id, sequence, digest),
        )

    def acknowledge(
        self, frame: Frame, *, expected_server_id: str, current_connection
    ) -> ReceiptCheckpoint:
        """Commit only a validated cumulative receipt-custody ACK.

        expected_server_id comes from local config. current_connection is the
        trusted live channel snapshot, sampled under its owner serialization;
        never construct either argument from the ACK payload. The channel owner
        still authenticates the peer and checks frame direction/message sequence.
        A successful send is NOT an ACK. No receipt, command or artifact is deleted.
        """
        from .authority import NodeConnectionIdentity

        _identifier(expected_server_id)
        if type(current_connection) is not NodeConnectionIdentity:
            raise invalid(1, "ACK requires trusted typed current connection facts")
        for value in (
            current_connection.node_id,
            current_connection.node_epoch,
            current_connection.gateway_owner_epoch,
        ):
            _identifier(value)
        _integer(current_connection.connection_generation)
        if not isinstance(frame, Frame) or frame.type != "reconcile-result":
            raise invalid(1, "Receipt ACK requires a reconcile-result frame")
        payload = frame.payload
        if (
            set(payload)
            != {
                "kind",
                "server-id",
                "log-incarnation-id",
                "connection-generation",
                "through-sequence",
                "through-receipt-sha256",
            }
            or payload["kind"] != "receipt-ack"
        ):
            raise invalid(1, "Invalid receipt ACK payload variant")
        log_id = _log_id(payload["log-incarnation-id"])
        sequence = _integer(payload["through-sequence"])
        digest = _digest(payload["through-receipt-sha256"])
        _integer(payload["connection-generation"])
        live_scope = (
            current_connection.node_id,
            current_connection.node_epoch,
            current_connection.gateway_owner_epoch,
        )
        if (
            live_scope != self._scope
            or (frame.node_id, frame.node_epoch, frame.gateway_owner_epoch) != live_scope
            or "unbound" in (current_connection.node_epoch, current_connection.gateway_owner_epoch)
            or payload["connection-generation"] != current_connection.connection_generation
            or payload["server-id"] != expected_server_id
        ):
            raise conflict(1, "Receipt ACK does not match trusted server and live connection")
        with self._transaction() as db:
            self._require_current(db)
            checkpoint = self._checkpoint(db)
            if log_id != checkpoint.log_incarnation_id or checkpoint.server_id not in (
                None,
                expected_server_id,
            ):
                raise conflict(1, "Receipt ACK targets another log or bound server")
            if sequence < checkpoint.through_sequence:
                raise conflict(1, "Receipt ACK cursor regressed")
            receipt = self._outbox_receipt(db, sequence)
            if receipt.digest != digest:
                raise conflict(1, "Receipt ACK digest does not match exact local receipt")
            if sequence == checkpoint.through_sequence:
                if digest != checkpoint.through_receipt_sha256:
                    raise conflict(1, "Duplicate receipt ACK digest changed")
                return checkpoint
            self._write_ack(db, expected_server_id, sequence, digest)
            return self._checkpoint(db)
