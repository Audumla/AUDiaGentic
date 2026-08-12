"""ON03: resolve_reconciliation_policy — first-run mode question + per-provider
prompt, built entirely on the existing foundation.interaction.ask() primitive
(use_backend() for injection, no bespoke ask_fn parameter)."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.interaction import AskRequest, AskResponse, ResponseStatus, use_backend

pytestmark = pytest.mark.no_parallel


class _ScriptedBackend:
    """Answers ask() by exact title match; anything unscripted times out."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.asked: list[AskRequest] = []

    def ask(self, request: AskRequest) -> AskResponse:
        self.asked.append(request)
        choice = self.answers.get(request.title)
        if choice is None:
            return AskResponse(status=ResponseStatus.TIMED_OUT)
        return AskResponse(status=ResponseStatus.ANSWERED, choice=choice)

    def push_status(self, msg) -> None:
        pass

    def respond(self, request_id: str, choice: str | None, *, details: dict) -> None:
        pass


_MODE_QUESTION = "How should audiagentic activate provider harnesses in this project?"


def _only_codex_and_claude_available(descriptor):
    available = descriptor.provider_id in ("codex", "claude")
    return {
        "available": available,
        "command": [descriptor.provider_id, "--version"],
        "executable": f"/usr/bin/{descriptor.provider_id}" if available else None,
        "returncode": 0 if available else None,
        "stdout": "1.0" if available else "",
        "stderr": "" if available else "not found",
    }


def _patch_probe(monkeypatch) -> None:
    import audiagentic.components.providers.services.lifecycle.lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "probe_provider_cli", _only_codex_and_claude_available)


def test_mode_question_asked_once_when_unconfigured(monkeypatch, tmp_path: Path) -> None:
    from audiagentic.components.providers.services.config.provider_config import (
        get_reconciliation_policy,
        is_reconciliation_policy_configured,
    )
    from audiagentic.components.providers.services.reconcile import resolve_reconciliation_policy

    _patch_probe(monkeypatch)
    backend = _ScriptedBackend({_MODE_QUESTION: "auto"})

    with use_backend(backend):
        resolve_reconciliation_policy(tmp_path)

    assert [r.title for r in backend.asked] == [_MODE_QUESTION]
    assert is_reconciliation_policy_configured(tmp_path) is True
    assert get_reconciliation_policy(tmp_path) == {"mode": "auto"}


def test_mode_question_not_asked_again_once_configured(monkeypatch, tmp_path: Path) -> None:
    from audiagentic.components.providers.services.config.provider_config import (
        set_reconciliation_policy,
    )
    from audiagentic.components.providers.services.reconcile import resolve_reconciliation_policy

    _patch_probe(monkeypatch)
    set_reconciliation_policy(tmp_path, mode="auto")
    backend = _ScriptedBackend({})

    with use_backend(backend):
        resolve_reconciliation_policy(tmp_path)

    assert backend.asked == []


def test_timed_out_mode_response_defaults_to_auto(monkeypatch, tmp_path: Path) -> None:
    from audiagentic.components.providers.services.config.provider_config import (
        get_reconciliation_policy,
    )
    from audiagentic.components.providers.services.reconcile import resolve_reconciliation_policy

    _patch_probe(monkeypatch)
    backend = _ScriptedBackend({})  # unscripted -> TIMED_OUT

    with use_backend(backend):
        resolve_reconciliation_policy(tmp_path)

    assert get_reconciliation_policy(tmp_path) == {"mode": "auto"}


def test_allowlist_mode_asks_only_cli_available_undecided_providers(
    monkeypatch, tmp_path: Path
) -> None:
    from audiagentic.components.providers.services.config.provider_config import (
        set_reconciliation_policy,
    )
    from audiagentic.components.providers.services.reconcile import resolve_reconciliation_policy

    _patch_probe(monkeypatch)
    set_reconciliation_policy(tmp_path, mode="allowlist")
    backend = _ScriptedBackend({"Enable codex?": "yes", "Enable claude?": "no"})

    with use_backend(backend):
        resolve_reconciliation_policy(tmp_path)

    asked_titles = {r.title for r in backend.asked}
    assert asked_titles == {"Enable codex?", "Enable claude?"}


def test_yes_answer_enables_the_provider_immediately(monkeypatch, tmp_path: Path) -> None:
    from audiagentic.components.providers.services.config.provider_config import (
        get_reconciliation_policy,
        is_provider_enabled,
        set_reconciliation_policy,
    )
    from audiagentic.components.providers.services.reconcile import resolve_reconciliation_policy

    _patch_probe(monkeypatch)
    set_reconciliation_policy(tmp_path, mode="allowlist")
    backend = _ScriptedBackend({"Enable codex?": "yes", "Enable claude?": "no"})

    with use_backend(backend):
        resolve_reconciliation_policy(tmp_path)

    assert is_provider_enabled(tmp_path, "codex") is True
    assert is_provider_enabled(tmp_path, "claude") is False

    policy = get_reconciliation_policy(tmp_path)
    assert policy["allowed-providers"] == ["codex"]
    assert set(policy["decided-providers"]) == {"claude", "codex"}


def test_already_decided_provider_is_not_asked_again(monkeypatch, tmp_path: Path) -> None:
    from audiagentic.components.providers.services.config.provider_config import (
        set_reconciliation_policy,
    )
    from audiagentic.components.providers.services.reconcile import resolve_reconciliation_policy

    _patch_probe(monkeypatch)
    set_reconciliation_policy(
        tmp_path, mode="allowlist", allowed_providers=["codex"], decided_providers=["codex"]
    )
    backend = _ScriptedBackend({"Enable claude?": "no"})

    with use_backend(backend):
        resolve_reconciliation_policy(tmp_path)

    asked_titles = {r.title for r in backend.asked}
    assert asked_titles == {"Enable claude?"}


def test_newly_detected_provider_asked_even_after_mode_already_configured(
    monkeypatch, tmp_path: Path
) -> None:
    """A provider that appears on PATH later must still surface as a decision
    point, even though the mode question itself was answered long ago."""
    from audiagentic.components.providers.services.config.provider_config import (
        set_reconciliation_policy,
    )
    from audiagentic.components.providers.services.reconcile import resolve_reconciliation_policy

    set_reconciliation_policy(
        tmp_path, mode="allowlist", allowed_providers=["codex"], decided_providers=["codex"]
    )

    import audiagentic.components.providers.services.lifecycle.lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "probe_provider_cli", _only_codex_and_claude_available)
    backend = _ScriptedBackend({"Enable claude?": "yes"})

    with use_backend(backend):
        resolve_reconciliation_policy(tmp_path)

    assert [r.title for r in backend.asked] == ["Enable claude?"]


def test_prompt_mode_no_tty_never_blocks_and_defaults_safely(monkeypatch, tmp_path: Path) -> None:
    """No backend configured at all (the real non-TTY/no-MCP-ctx case) must
    not hang and must not raise."""
    from audiagentic.components.providers.services.config.provider_config import (
        get_reconciliation_policy,
    )
    from audiagentic.components.providers.services.reconcile import resolve_reconciliation_policy

    _patch_probe(monkeypatch)

    resolve_reconciliation_policy(tmp_path)  # no use_backend() at all

    assert get_reconciliation_policy(tmp_path) == {"mode": "auto"}
