"""``audiagentic qualify --live`` is explicit, needs a provider and reports honestly."""
from __future__ import annotations

import argparse
import json

from audiagentic.commands import qualify as command


def _args(**kw):
    return argparse.Namespace(**{"provider": None, "provider_option": None, "surface": None, "as_json": True, "live": True, **kw})


def test_live_needs_a_provider(capsys):
    assert command.run_qualify_command(_args()) == command.EXIT_UNKNOWN
    assert "--live needs a provider" in capsys.readouterr().out


def test_live_with_an_unknown_provider_is_a_clean_error(capsys):
    assert command.run_qualify_command(_args(provider="nobody")) == command.EXIT_UNKNOWN
    assert "no live qualification probes" in json.loads(capsys.readouterr().out)["error"]


def test_live_exit_code_follows_the_state(monkeypatch, capsys):
    from audiagentic.components.providers.services.qualification import live

    result = {"provider": "codex", "surface": "s", "state": "partial", "capabilities": {"passive-identity": True},
              "reasons": [], "evidence-id": "qe_x", "claim": "c"}
    monkeypatch.setattr(live, "qualify_live", lambda provider: result)
    assert command.run_qualify_command(_args(provider="codex", as_json=False)) == 0
    assert "partial" in capsys.readouterr().out
    monkeypatch.setattr(live, "qualify_live", lambda provider: {**result, "state": "inconclusive"})
    assert command.run_qualify_command(_args(provider="codex")) == command.EXIT_FAILED


def test_the_default_qualify_never_runs_probes(monkeypatch):
    called = []
    from audiagentic.components.providers.services.qualification import live

    monkeypatch.setattr(live, "qualify_live", lambda provider: called.append(provider))
    monkeypatch.setattr("audiagentic.components.providers.services.qualification.qualifier.qualify", lambda *a: [])
    assert command.run_qualify_command(_args(live=False)) == 0 and not called
