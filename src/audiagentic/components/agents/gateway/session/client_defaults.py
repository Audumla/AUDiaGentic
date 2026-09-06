"""SH33: gateway-owned GPT default bindings, keyed by lease client/project/agent.

Binding selection is serialized only across admission, never across a model turn.
Provider URLs remain private recovery evidence, not part of compact status.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import weakref
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.system.process import StartupLock

_guards_lock = threading.Lock()
_guards: Any = weakref.WeakValueDictionary()


def preparation_guard(record: dict[str, Any]) -> Any:
    identity = record.get("client-default-session")
    if not isinstance(identity, dict):
        return threading.RLock()
    key = identity["key"]
    with _guards_lock:
        return _guards.setdefault(key, threading.RLock())


def scope_key(client_id: str, project_root: Path, agent_id: str) -> str:
    parts = [client_id, os.path.normcase(str(project_root.resolve())), agent_id]
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def _path(service_root: Path, key: str) -> Path:
    if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
        raise ValueError("invalid client default binding key")
    return service_root / "client-default-sessions" / (key + ".json")


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid client default binding")
    return value


def chat_url(metadata: dict[str, Any]) -> str | None:
    from audiagentic.components.providers.adapters.gpt_auto.urls import canonical_chat_url, parse_project_id

    for key in ("chat-url", "provider-chat-url"):
        value = metadata.get(key)
        if isinstance(value, str) and (url := canonical_chat_url(value)):
            return url
    project = metadata.get("project-url")
    conversation = metadata.get("provider-session-id")
    if isinstance(project, str) and isinstance(conversation, str) and parse_project_id(project):
        return canonical_chat_url(f"https://chatgpt.com/g/{parse_project_id(project)}/c/{conversation}")
    return None


def warning(code: str, message: str, session_id: str | None = None) -> dict[str, str]:
    # Only gateway-authored messages are public. Never copy provider exception
    # text, which can contain private URLs, DOM, filesystem paths or prompts.
    result = {"code": code[:80], "message": message[:240]}
    if session_id:
        result["session-id"] = session_id
    return result


def proven_unsent_composer_failure(error: Exception) -> bool:
    """Only explicit provider proof allows retrying a stateful prompt."""
    return (
        isinstance(error, AudiaGenticError)
        and error.code == "EXT-GPTAUTO-003"
        and error.details.get("failure-reason") == "composer-operation-timeout"
        and error.details.get("submission-ambiguous") is False
    )


@dataclass
class Selection:
    session_id: str | None
    provider_chat_url: str | None
    path: Path | None = None
    binding: dict[str, Any] = field(default_factory=dict)
    automatic: bool = False
    warnings: list[dict[str, str]] = field(default_factory=list)

    @property
    def identity(self) -> dict[str, Any] | None:
        return {"key": self.path.stem, "automatic": self.automatic} if self.path else None

    def commit(self, record: dict[str, Any]) -> None:
        if self.path is None:
            return
        if not self.binding or self.automatic:
            data = dict(self.binding)
            data["session-id"] = record["session-id"]
            if self.provider_chat_url:
                data["chat-url"] = self.provider_chat_url
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self.path, data)


@contextmanager
def select(
    project_root: Path, *, service_root: str | None, client_id: str | None,
    agent_id: str | None, provider_id: str, session_id: str | None,
    provider_chat_url: str | None, new_session: bool,
) -> Iterator[Selection]:
    if not (service_root and client_id and agent_id and provider_id.startswith("gpt-auto")):
        yield Selection(session_id, provider_chat_url)
        return
    path = _path(Path(service_root), scope_key(client_id, project_root, agent_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    with StartupLock(path.with_suffix(".lock")):
        binding = _read(path)
        automatic = not (session_id or provider_chat_url or new_session)
        selection = Selection(session_id, provider_chat_url, path, binding, automatic)
        if automatic and binding.get("session-id"):
            from audiagentic.components.agents.gateway.session import sessions_store

            selection.session_id = str(binding["session-id"])
            try:
                session = sessions_store.read_session_record(project_root, selection.session_id)
                recovered_url = chat_url(sessions_store.session_provider_metadata(session))
                if recovered_url:
                    binding["chat-url"] = recovered_url
            except AudiaGenticError as exc:
                selection.session_id = None
                selection.provider_chat_url = binding.get("chat-url")
                selection.warnings.append(warning(exc.code, "Default gateway session unavailable; restoring its chat when possible, otherwise creating a replacement.", str(binding["session-id"])))
        yield selection


def remember(project_root: Path, record: dict[str, Any]) -> None:
    """Capture provider metadata and auto-resume successors only for this default."""
    identity = record.get("client-default-session")
    root = record.get("dispatch-service-root")
    if not isinstance(identity, dict) or not root:
        return
    path = _path(Path(root), identity["key"])
    with StartupLock(path.with_suffix(".lock")):
        binding = _read(path)
        candidates = {record.get("session-id"), record.get("continuation-session-id")}
        if binding.get("session-id") not in candidates:
            return
        binding["session-id"] = record["session-id"]
        metadata = dict(record.get("provider-metadata") or {})
        from audiagentic.components.agents.gateway.session import sessions_store
        try:
            session = sessions_store.read_session_record(project_root, record["session-id"])
            metadata = {**sessions_store.session_provider_metadata(session), **metadata}
        except AudiaGenticError:
            pass
        url = chat_url(metadata)
        if url:
            binding["chat-url"] = url
        atomic_write_json(path, binding)


def redirect_if_replaced(project_root: Path, record: dict[str, Any]) -> dict[str, Any]:
    """Queued implicit requests follow a replacement established by earlier work."""
    identity = record.get("client-default-session")
    if not isinstance(identity, dict) or not identity.get("automatic"):
        return record
    path = _path(Path(record["dispatch-service-root"]), identity["key"])
    with StartupLock(path.with_suffix(".lock")):
        binding = _read(path)
        target = binding.get("session-id")
        if not target or target == record.get("session-id"):
            return record
        return _attach(project_root, record, target, warning("SH33-DEFAULT-REPLACED", "Using the client's replacement default session.", target), None)


def _attach(project_root: Path, record: dict[str, Any], target: str, note: dict[str, str], url: str | None) -> dict[str, Any]:
    from audiagentic.components.agents.gateway import store
    return store.update_owned_running_session(
        project_root, record["request-id"], owner_epoch=record["dispatch-owner-epoch"],
        worker_id=record["worker-id"], attempt_epoch=record["attempt-epoch"],
        session_id=target, warnings=[*(record.get("warnings") or []), note][-3:],
        recovery_chat_url=url,
    )


def replace_failed_default(project_root: Path, record: dict[str, Any], error: Exception, *, recover_url: bool, attach_request: bool = True) -> dict[str, Any] | None:
    """Prepare a replacement before prompt submission; preserve prior failure evidence."""
    if proven_unsent_composer_failure(error):
        return None
    identity = record.get("client-default-session")
    if not isinstance(identity, dict) or not identity.get("automatic"):
        return None
    from audiagentic.components.agents.gateway.session import sessions_store

    # Preserve the cause before replacing the default; the public warning
    # intentionally omits exception text, but protected attempt history must
    # retain it for diagnosis even when the fallback later succeeds.
    from audiagentic.components.agents.gateway import store
    store.append_owned_attempt(
        project_root, record["request-id"],
        owner_epoch=record["dispatch-owner-epoch"], worker_id=record["worker-id"],
        attempt_epoch=record["attempt-epoch"],
        execution_profile_id=record["execution-profile-id"],
        provider_id=record["resolved-provider-id"], model_id=record.get("resolved-model-id"),
        state="failed", error=error,
    )
    path = _path(Path(record["dispatch-service-root"]), identity["key"])
    with StartupLock(path.with_suffix(".lock")):
        binding = _read(path)
        existing = binding.get("session-id")
        if existing and existing != record.get("session-id"):
            note = warning("SH33-DEFAULT-REPLACED", "A replacement default already exists; this prompt was not replayed." if not attach_request else "Using the client's replacement default session.", existing)
            return _attach(project_root, record, existing if attach_request else record["session-id"], note, None)
        url = binding.get("chat-url") if recover_url else None
        try:
            source = sessions_store.read_session_record(project_root, record["session-id"])
            if recover_url:
                url = chat_url(sessions_store.session_provider_metadata(source)) or url
        except AudiaGenticError:
            pass
        session = sessions_store.build_session_record(
            created_by_request_id=record["request-id"], provider_transport_kind="provider-session",
            execution_profile_id=record["execution-profile-id"], provider_id=record["resolved-provider-id"],
            model_id=record.get("resolved-model-id"),
        )
        sessions_store.write_session_record(project_root, session)
        target = session["session-id"]
        code = error.code if isinstance(error, AudiaGenticError) else "INT-AGW-098"
        note = warning(code, "Default session failed; attempting retained chat recovery." if url else "Default session failed; using a new chat.", record.get("session-id"))
        if not attach_request:
            note = warning(code, "Default session failed; a replacement default is reserved. This prompt was not replayed.", target)
        updated = _attach(project_root, record, target if attach_request else record["session-id"], note, url if attach_request else None)
        atomic_write_json(path, {"session-id": target, **({"chat-url": url} if url else {})})
        return updated
