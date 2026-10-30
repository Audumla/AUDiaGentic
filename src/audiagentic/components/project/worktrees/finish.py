"""Finishing a merged task worktree (DW01 ``worktree finish``).

One locked, journaled sequence for exactly one worktree: fetch the default
branch, fence new work, assess (``eligibility``), preserve, assess again and
compare, then remove with plain non-force git and delete the branch only if it
still points where it did. Preservation comes first and is never undone here:
an immutable ``refs/quarantine/<id>`` ref at the tip, and a verified copy of
the project's ignored record files in the central archive. The journal records
each phase so a crash resumes instead of guessing, and a refusal at any point
before the worktree is removed lifts the fence and leaves everything as it was.
Only merged work is finished here; abandoning unmerged work is a separate step.

Known limits, documented rather than solved: a process that ignores the drain fence and
writes into the worktree between the final check and the removal cannot be stopped by
these checks alone; there is no archive size quota (a full disk refuses before removal);
partially written ``.partial`` archive directories from a failed attempt are left for
inspection, never deleted; and the state directory is trusted to be private to the user.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.paths.home import user_state_dir
from audiagentic.foundation.system import forge, git, worktree_drain
from audiagentic.foundation.system.advisory_lock import AdvisoryLock
from audiagentic.foundation.time import now_iso_z

from . import eligibility, records

refuse_error = make_error_factory("CON", "WTFIN", "project")

PHASES = ("PREPARED", "DRAINED", "PRESERVED", "REMOVING", "WORKTREE_REMOVED", "BRANCH_REMOVED", "COMPLETE")


def _key(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:16]


def _journal_path(state: Path, repo: Path, path: Path) -> Path:
    return state / "worktrees" / "journal" / records.repo_id(repo) / f"{_key(path)}.json"


def _write_journal(file: Path, body: dict[str, Any], phase: str) -> None:
    body["phase"] = phase
    body.setdefault("phases", {})[phase] = now_iso_z()
    file.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(file, body)


def _read_journal(file: Path) -> dict[str, Any] | None:
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _resolve_target(repo: Path, target: str) -> Path:
    entries = git.list_worktrees(repo)
    if "/" in target or target.startswith("."):
        return Path(target).expanduser().resolve()
    matches = [e for e in entries[1:] if e.branch == target or (e.branch or "").rsplit("/", 1)[-1] == target
               or e.path.name == target]
    if len(matches) != 1:
        raise refuse_error(1, "The target does not name exactly one worktree; give its absolute path",
                           target=target, matches=len(matches))
    return matches[0].path


def _digest(root: Path) -> dict[str, tuple]:
    """Relative path to a fingerprint for everything under ``root``, without following symlinks.

    Regular files are ``("file", size, sha256)``, symlinks ``("link", target text)``. Anything else
    (FIFOs, sockets, devices) cannot be archived faithfully, so it refuses.
    """
    result: dict[str, tuple] = {}
    for current, directories, files in os.walk(root, followlinks=False):
        for name in [*directories, *files]:
            file = Path(current) / name
            mode = file.lstat().st_mode
            relative = file.relative_to(root).as_posix()
            if stat.S_ISLNK(mode):
                result[relative] = ("link", os.readlink(file))
            elif stat.S_ISREG(mode):
                digest = hashlib.sha256()
                with file.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1 << 20), b""):
                        digest.update(chunk)
                result[relative] = ("file", file.lstat().st_size, digest.hexdigest())
            elif stat.S_ISDIR(mode):
                result[relative] = ("dir",)  # empty directories can be intentional state
            else:
                raise refuse_error(5, "A record file is not a regular file or symlink and cannot be archived",
                                   entry=relative)
    return result


def _entry_digest(worktree: Path, entry: str) -> dict[str, tuple]:
    """Fingerprint of one ignored record entry (a file, a symlink or a directory tree)."""
    source = worktree / entry.rstrip("/")
    mode = source.lstat().st_mode
    if stat.S_ISDIR(mode):
        return _digest(source)
    return _digest_single(source)


def _digest_single(file: Path) -> dict[str, tuple]:
    mode = file.lstat().st_mode
    if stat.S_ISLNK(mode):
        return {"": ("link", os.readlink(file))}
    if stat.S_ISREG(mode):
        return {"": ("file", file.lstat().st_size, hashlib.sha256(file.read_bytes()).hexdigest())}
    raise refuse_error(5, "A record file is not a regular file or symlink and cannot be archived", entry=file.name)


def _archive_records(worktree: Path, entries: list[str], destination: Path) -> int:
    """Copy the project's ignored record files into a NEW archive directory and verify them.

    The copy is staged beside the destination and renamed into place only once it matches, so a
    published archive is never modified and nothing is ever deleted here.
    """
    staging = destination.with_name(destination.name + ".partial")
    staging.mkdir(parents=True, exist_ok=False)
    for entry in entries:
        source = worktree / entry.rstrip("/")
        target = staging / entry.rstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        before = _entry_digest(worktree, entry)
        if source.is_symlink():
            os.symlink(os.readlink(source), target)
        elif source.is_dir():
            shutil.copytree(source, target, symlinks=True)
        else:
            shutil.copy2(source, target, follow_symlinks=False)
        copied = _digest(target) if target.is_dir() and not target.is_symlink() else _digest_single(target)
        if before != copied or before != _entry_digest(worktree, entry):
            raise refuse_error(5, "The archive copy does not match the original; nothing was removed", entry=entry)
    staging.rename(destination)
    return len(entries)


def _identity(path: Path, repo: Path) -> dict[str, Any]:
    """What makes this directory this worktree: the repository, its inode and git's pointer file."""
    status = path.stat()
    pointer = path / ".git"
    return {"common-dir": str(git.common_dir(repo)), "inode": [status.st_dev, status.st_ino],
            "gitdir": pointer.read_text(encoding="utf-8").strip() if pointer.is_file() else None}


def _proof(assessment: eligibility.Assessment, repo: Path) -> dict[str, Any]:
    pr = assessment.pull_request
    unknown, records_found, _ = eligibility.classify_ignored(assessment.path, git.ignored_entries(assessment.path))
    return {"branch": assessment.branch, "head": assessment.head,
            "pr": None if pr is None else pr.number, "merge-commit": None if pr is None else pr.merge_commit,
            "identity": _identity(assessment.path, repo), "ignored": sorted(unknown),
            "records": sorted(records_found)}


def _assess(repo: Path, path: Path, *, active_work, pull_requests) -> tuple[git.WorktreeEntry, eligibility.Assessment]:
    entries = git.list_worktrees(repo)
    entry = next((e for e in entries if e.path == path), None)
    if entry is None or entry == entries[0]:
        raise refuse_error(1, "That path is not a removable worktree of this repository", path=str(path))
    assessment = eligibility.assess_one(
        repo, entry, primary=False, protected=eligibility.service.protected_paths(repo),
        base=git.default_branch(repo), active_work=active_work, pull_requests=pull_requests)
    return entry, assessment


def _require_eligible(path: Path, assessment: eligibility.Assessment, discard_ignored: int | None) -> None:
    blockers = list(assessment.blockers)
    ignored = [b for b in blockers if b.code == "ignored-files"]
    if ignored:
        unknown, _, _ = eligibility.classify_ignored(path, git.ignored_entries(path))
        if discard_ignored != len(unknown):
            raise refuse_error(3, f"{len(unknown)} ignored entries would be lost; review them and repeat with "
                                  f"discard-ignored {len(unknown)}", count=len(unknown), entries=unknown[:5])
        blockers = [b for b in blockers if b.code != "ignored-files"]
    if blockers:
        raise refuse_error(2, "This worktree cannot be finished: "
                              + "; ".join(f"{b.code}: {b.detail}" for b in blockers[:4]),
                           blockers=[b.code for b in blockers])


def finish(repo: Path, target: str, *, active_work, discard_ignored: int | None = None,
           pull_requests=forge.pull_requests_for_branch, state_root: Path | None = None) -> dict[str, Any]:
    """Preserve, then remove, the merged worktree ``target``; refuse on anything uncertain."""
    main = git.list_worktrees(repo)[0].path
    state = state_root or user_state_dir()
    path = _resolve_target(repo, target)
    journal_file = _journal_path(state, repo, path)
    lock = state / "worktrees" / f"{records.repo_id(repo)}.finish.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with AdvisoryLock(lock, timeout=60.0):
        journal = _read_journal(journal_file)
        present = any(e.path == path for e in git.list_worktrees(repo))
        if not present:
            if (journal and PHASES.index(journal["phase"]) >= PHASES.index("REMOVING")
                    and journal["proof"]["identity"]["common-dir"] == str(git.common_dir(repo))
                    and git.resolve_commit(main, journal.get("quarantine-ref", "")) == journal["proof"]["head"]):
                return _finish_tail(main, repo, path, journal, journal_file, state)
            raise refuse_error(1, "That path is not a removable worktree of this repository", path=str(path))

        base = git.default_branch(main)
        if base is None:
            raise refuse_error(6, "The remote default branch is unknown; refusing without a base to prove against")
        remote, _, base_branch = base.partition("/")
        try:
            git.fetch(main, remote, base_branch)
        except Exception as error:
            raise refuse_error(6, "Could not fetch the remote default branch; refusing to judge against a stale one") from error

        if journal:  # an earlier transaction's evidence is kept, never overwritten
            journal_file.rename(journal_file.with_name(f"{journal_file.stem}.{journal.get('transaction', 'old')}.json"))
        worktree_drain.begin(path, reason="finish", state_root=state)
        removed = False
        try:
            _, first = _assess(repo, path, active_work=active_work, pull_requests=pull_requests)
            _require_eligible(path, first, discard_ignored)
            paired = records.reconcile(git.list_worktrees(repo), records.read_records(repo, state_root=state)).paired
            record = paired.get(path)
            body = {"transaction": uuid.uuid4().hex, "path": str(path), "proof": _proof(first, repo),
                    "record-id": record.worktree_id if record else None, "started": now_iso_z()}
            _write_journal(journal_file, body, "PREPARED")
            _write_journal(journal_file, body, "DRAINED")

            reference = f"refs/quarantine/{_key(path)}/{body['transaction'][:12]}"
            git.create_ref(main, reference, first.head)
            if git.resolve_commit(main, reference) != first.head:
                raise refuse_error(5, "The quarantine ref does not point at the worktree tip; nothing was removed")
            archive = (state / "worktrees" / "archive" / records.repo_id(repo)
                       / f"{_key(path)}-{first.head[:9]}-{body['transaction'][:8]}")
            archived = _archive_records(path, body["proof"]["records"], archive) if body["proof"]["records"] else 0
            body.update({"quarantine-ref": reference, "archive": str(archive) if archived else None})
            if hasattr(os, "sync"):
                os.sync()  # archive and ref reach disk before anything is removed
            _write_journal(journal_file, body, "PRESERVED")

            _, second = _assess(repo, path, active_work=active_work, pull_requests=pull_requests)
            _require_eligible(path, second, discard_ignored)
            if _proof(second, repo) != body["proof"]:
                raise refuse_error(4, "The worktree changed while it was being finished; nothing was removed",
                                   before=body["proof"], after=_proof(second, repo))
            for entry in body["proof"]["records"]:  # the archive must still equal the live records
                if _entry_digest(path, entry) != _digest_entry_in(archive, entry):
                    raise refuse_error(4, "A record file changed after it was archived; nothing was removed", entry=entry)
            _write_journal(journal_file, body, "REMOVING")
            removed = True  # from here the directory may be half gone: the fence stays until the tail ends
            try:
                git.remove_clean_worktree(main, path)
            except Exception as error:
                if _intact(repo, path, first.head):
                    removed = False  # git refused and the worktree is provably as it was
                raise refuse_error(7, "git refused to remove the worktree; nothing was forced",
                                   reason=getattr(error, "details", None)) from error
            _write_journal(journal_file, body, "WORKTREE_REMOVED")
        finally:
            if not removed:
                worktree_drain.end(path, state_root=state)
        return _finish_tail(main, repo, path, body, journal_file, state)


def _intact(repo: Path, path: Path, tip: str) -> bool:
    """Whether a worktree git failed to remove is still registered, clean and at the recorded tip."""
    try:
        entry = next((e for e in git.list_worktrees(repo) if e.path == path), None)
        return entry is not None and path.is_dir() and entry.head == tip and git.changes(path) == (0, 0)
    except Exception:  # noqa: BLE001 - cannot tell means not provably intact
        return False


def _digest_entry_in(archive: Path, entry: str) -> dict[str, tuple]:
    return _entry_digest(archive, entry)


def _finish_tail(main: Path, repo: Path, path: Path, body: dict[str, Any], journal_file: Path,
                 state: Path) -> dict[str, Any]:
    """The steps after the worktree is gone; each is idempotent so a crashed finish resumes here.

    The fence is lifted only once the whole tail has completed; a failure leaves it in place.
    """
    proof = body["proof"]
    branch, tip = proof["branch"], proof["head"]
    notes: list[str] = []
    if branch and git.branch_exists(main, branch):
        if git.resolve_commit(main, f"refs/heads/{branch}") == tip:
            git.delete_branch_at(main, branch, tip)
        else:
            notes.append(f"branch {branch} moved since the tip was recorded; it was left in place")
    _write_journal(journal_file, body, "BRANCH_REMOVED")
    recorded = records.read_records(repo, state_root=state).get(body.get("record-id") or "")
    if recorded is not None and Path(recorded.path).resolve() == path:
        records.forget(repo, recorded.worktree_id, state_root=state)
    _write_journal(journal_file, body, "COMPLETE")
    worktree_drain.end(path, state_root=state)
    return {"path": str(path), "branch": branch, "tip": tip, "pr": proof["pr"],
            "quarantine-ref": body.get("quarantine-ref"), "archive": body.get("archive"), "notes": notes}
