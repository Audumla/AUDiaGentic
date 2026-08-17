"""GP07 live adversarial stress scenarios against the real gpt-t1/gpt-t2
ChatGPT test projects.

MANUAL-ONLY -- deliberately excluded from normal test runs (pytest.ini/CI
never sets AUDIAGENTIC_GPT_AUTO_LIVE, so a plain `pytest` run always skips
this whole module). Do not wire this into CI or any automated pipeline.
Run it explicitly and sparingly:

    AUDIAGENTIC_GPT_AUTO_LIVE=1 python -m pytest tests/gpt_auto/test_live_stress_scenarios.py -v

Why manual-only, not automated:
- Each test drives a real ChatGPT account through a real browser and
  consumes real usage against gpt-t1/gpt-t2. There is no sandbox/mock mode.
- ChatGPT itself rate-limits aggressively on NEW SESSION creation more than
  on continuing an existing one (proven live 2026-08-16) -- running these
  back-to-back, or as part of a routine/scheduled suite, risks tripping a
  real account-level rate limit (or worse) that then blocks unrelated work
  on the SAME shared gpt-auto accounts/projects used by other sessions.
  See docs/planning/active/gpt-auto-conversation/GP04.md's notes for the
  live incident this caused.
- Real generation timing is highly variable (single-digit seconds to
  multi-minute) and genuinely nondeterministic -- these are stress/
  exploration scenarios for a human to run and read the output of, not
  a reliable pass/fail gate to block merges on.
- Some scenarios deliberately interfere with a live browser tab (closing
  it mid-generation, cancelling mid-generation) -- not something that
  should run unattended.

Session usage: 3 test functions, 4 real ChatGPT sessions total (not one
per scenario) -- test_live_t1_scenarios runs the long-generation and
tab-close scenarios sequentially against ONE gpt-t1 session; the cancel
scenario reuses its own session for its follow-up prompt; only the
concurrent-isolation test genuinely needs two simultaneous sessions.
ChatGPT rate-limits new-session creation more than continuing an existing
one (proven live 2026-08-16), so minimizing session count here is
deliberate, not incidental -- do not "simplify" this back to one fresh
session per scenario.

Requires:
- A real Chrome/Brave already running with --remote-debugging-port=9222
  (or whatever port .audiagentic/config/providers/gpt-auto-t1.yaml points
  at), logged into ChatGPT.
- The local, gitignored .audiagentic/config/providers/gpt-auto-t1.yaml and
  gpt-auto-t2.yaml provider settings files to exist (they carry the real
  gpt-t1/gpt-t2 project URLs -- see GP05). Tests skip individually if a
  required settings file is missing rather than failing the whole module,
  since these files are machine-local and not committed.

These drive the real production entry point (session_transport.py's
build_session_transport -> GptAutoSessionTransport, wrapping a real
PersistentChat + GptAutoTurn) directly, bypassing the gateway/MCP layers,
so failures point straight at the adapter rather than the dispatch stack.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest

from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
    build_session_transport,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import load_yaml_file
from audiagentic.foundation.transports.agent_session import (
    SessionControlAction,
    SessionControlRequest,
    SessionPrompt,
)

# Real ChatGPT generations genuinely take minutes, not the 30s global
# pytest-timeout default (pyproject.toml) -- these are long_running by the
# project's own convention (see tests/TESTING.md's Timeouts section) and
# must carry an explicit override, not rely on the global safety net.
pytestmark = [
    pytest.mark.skipif(
        os.environ.get("AUDIAGENTIC_GPT_AUTO_LIVE") != "1",
        reason="set AUDIAGENTIC_GPT_AUTO_LIVE=1 to run against a real ChatGPT browser",
    ),
    pytest.mark.long_running,
    pytest.mark.timeout(600),
]

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_live_settings(provider_id: str) -> dict[str, Any]:
    path = _PROJECT_ROOT / ".audiagentic" / "config" / "providers" / f"{provider_id}.yaml"
    if not path.exists():
        pytest.skip(f"{path} not present -- local gpt-t1/t2 test-project config not set up")
    data = load_yaml_file(path)
    settings = data.get("settings", data)
    if not isinstance(settings, dict):
        pytest.skip(f"{path} has no usable settings block")
    return settings


_CHECKPOINT_DIR = _PROJECT_ROOT / ".audiagentic" / "runtime" / "live-stress-checkpoints"


def _make_checkpoint_sink(ag_session_id: str):
    """GP11: a real checkpoint_sink so an ambiguous live failure can
    actually be reconciled afterward (read-only CDP inspection against a
    known baseline/turn-id) instead of being unrecoverable once a tab
    closes, as happened during tonight's investigation. This is a minimal
    local-file sink, not the gateway's durable session-store one -- this
    test harness deliberately bypasses the gateway/session store (see
    module docstring), so there's no session record to write into. Good
    enough to leave a trail on disk for manual/agent-assisted reconciliation."""
    path = _CHECKPOINT_DIR / f"{ag_session_id}.json"

    def _sink(metadata: dict[str, Any]) -> None:
        _CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
        if metadata.get("unresolved-turn-pending"):
            path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
        elif path.exists():
            path.unlink()

    return _sink


async def _open_transport(provider_id: str):
    settings = _load_live_settings(provider_id)
    config = GptAutoConfig.from_project_dict(settings)
    ag_session_id = f"live-stress-{uuid.uuid4().hex[:12]}"
    transport = build_session_transport(
        _PROJECT_ROOT,
        config=settings,
        ag_session_id=ag_session_id,
        binding_sink=lambda _update: None,
        checkpoint_sink=_make_checkpoint_sink(ag_session_id),
    )
    await transport.open()
    return transport, config


async def _find_live_cdp_target(cdp_url: str, url_fragment: str) -> str | None:
    """Poll the browser's /json endpoint for a tab whose URL contains
    url_fragment. Used only to locate a target for deliberate interference
    (closing it mid-turn) -- not part of the adapter itself."""
    import json
    import urllib.request

    base = cdp_url.replace("ws://", "http://").replace("wss://", "https://")
    if not base.startswith("http"):
        base = f"http://{base}"
    try:
        data = urllib.request.urlopen(f"{base}/json", timeout=5).read()
    except Exception:  # noqa: BLE001 - best-effort discovery for a test helper
        return None
    for tab in json.loads(data):
        if tab.get("type") == "page" and url_fragment in (tab.get("url") or ""):
            return tab.get("id")
    return None


async def _close_cdp_target(cdp_url: str, target_id: str) -> None:
    import urllib.request

    base = cdp_url.replace("ws://", "http://").replace("wss://", "https://")
    if not base.startswith("http"):
        base = f"http://{base}"
    urllib.request.urlopen(f"{base}/json/close/{target_id}", timeout=5)


async def _run_long_generation(transport) -> None:
    """L1: a genuinely long, multi-minute generation must complete with the
    full expected content, not time out or truncate."""
    observations: list[Any] = []
    result = await transport.prompt(
        SessionPrompt(
            turn_id=f"turn-{uuid.uuid4().hex[:8]}",
            body=(
                "Write a detailed, well-structured 2000+ word technical essay on "
                "how B-tree and LSM-tree storage engines differ, covering write "
                "amplification, read amplification, compaction strategies, and "
                "when each is the right choice. Use headings. Go deep."
            ),
        ),
        observations.append,
    )
    assert result.stop_reason == "end-turn"
    assert result.final_summary is not None
    assert len(result.final_summary) > 2000
    # NOTE: do not assert on the number of response-progress ACTIVITY
    # observations. If the response is already fully rendered by the
    # time submission-proof hands off to response-wait (a genuinely
    # fast completion, observed live -- ChatGPT response time varies
    # a lot), there is no text delta left for response-wait to detect
    # as an edge, so zero progress ticks is legitimate, not a bug.
    # The real acceptance criteria are the terminal state and content
    # above; progress-event *count* is not a safe invariant to assert.


@pytest.mark.asyncio
async def test_live_concurrent_turns_on_both_test_projects_stay_isolated():
    """L3: two long-running turns on gpt-t1 and gpt-t2 at the same time must
    not interfere with each other -- each completes with its own correct,
    distinct content."""
    transport_1, _ = await _open_transport("gpt-auto-t1")
    transport_2, _ = await _open_transport("gpt-auto-t2")
    try:
        result_1, result_2 = await asyncio.gather(
            transport_1.prompt(
                SessionPrompt(
                    turn_id=f"turn-{uuid.uuid4().hex[:8]}",
                    body="Reply with exactly the single word: FIRSTPROJECT",
                ),
                lambda _obs: None,
            ),
            transport_2.prompt(
                SessionPrompt(
                    turn_id=f"turn-{uuid.uuid4().hex[:8]}",
                    body="Reply with exactly the single word: SECONDPROJECT",
                ),
                lambda _obs: None,
            ),
        )
        assert result_1.stop_reason == "end-turn"
        assert result_2.stop_reason == "end-turn"
        assert "FIRSTPROJECT" in (result_1.final_summary or "")
        assert "SECONDPROJECT" in (result_2.final_summary or "")
        assert "SECONDPROJECT" not in (result_1.final_summary or "")
        assert "FIRSTPROJECT" not in (result_2.final_summary or "")
    finally:
        await transport_1.close()
        await transport_2.close()


async def _run_mid_turn_tab_close(transport, config) -> None:
    """L4: closing the real ChatGPT tab mid-generation must not corrupt the
    turn -- the adapter should recover (reopen the conversation) and still
    reach a correct terminal outcome, never a silent false success and
    never an indefinite hang (bounded by the turn's own absolute ceiling)."""
    prompt_task = asyncio.create_task(
        transport.prompt(
            SessionPrompt(
                turn_id=f"turn-{uuid.uuid4().hex[:8]}",
                body=(
                    "Write a detailed, well-structured 2000+ word technical essay on "
                    "the CAP theorem and its practical implications for distributed "
                    "database design. Use headings. Go deep."
                ),
            ),
            lambda _obs: None,
        )
    )
    # Give it a real head start into generation before interfering.
    await asyncio.sleep(15)
    target_fragment = str(config.project_url).rsplit("/", 1)[-1]
    target_id = None
    for _ in range(10):
        target_id = await _find_live_cdp_target(config.cdp_url, target_fragment)
        if target_id:
            break
        await asyncio.sleep(2)
    if target_id is None:
        prompt_task.cancel()
        pytest.skip("could not locate the live gpt-t1 tab to interfere with")
    await _close_cdp_target(config.cdp_url, target_id)

    result = await prompt_task
    assert result.stop_reason == "end-turn"
    assert result.final_summary is not None
    assert len(result.final_summary) > 500


@pytest.mark.asyncio
async def test_live_t1_scenarios():
    """L1 + L4 share one gpt-auto-t1 session (sequentially) instead of each
    opening a fresh conversation -- ChatGPT rate-limits new-session creation
    more aggressively than continuing an existing one (proven live
    2026-08-16, see GP04's notes), so this file conserves sessions rather
    than opening one per scenario."""
    transport, config = await _open_transport("gpt-auto-t1")
    try:
        await _run_long_generation(transport)
        await _run_mid_turn_tab_close(transport, config)
    finally:
        await transport.close()


@pytest.mark.asyncio
async def test_live_cancel_mid_turn_leaves_session_usable():
    """L5: cancelling mid-generation must terminate cleanly (no crash, no
    corrupted session state) and the session must remain usable for a
    follow-up turn afterward."""
    transport, _config = await _open_transport("gpt-auto-t2")
    try:
        turn_id = f"turn-{uuid.uuid4().hex[:8]}"
        prompt_task = asyncio.create_task(
            transport.prompt(
                SessionPrompt(
                    turn_id=turn_id,
                    body=(
                        "Write a detailed, well-structured 2000+ word technical essay on "
                        "the design of write-ahead logs in databases. Use headings."
                    ),
                ),
                lambda _obs: None,
            )
        )
        await asyncio.sleep(10)
        control_result = await transport.control(
            SessionControlRequest(
                ag_session_id=transport.ag_session_id,
                action=SessionControlAction.CANCEL_TURN,
                turn_id=turn_id,
            )
        )
        assert control_result.disposition.value in {"accepted", "already-terminal"}

        # Cancellation resolves gracefully (SessionTurnResult with
        # stop_reason="cancelled"), it does not raise -- proven live
        # 2026-08-16, turn.py's cancel() -> _result("cancelled") path.
        # ChatGPT's own completion time is highly variable (proven live,
        # anywhere from ~9s to multi-minute) -- the turn can legitimately
        # finish before the cancel takes effect, which is not a defect,
        # so "end-turn" is an accepted outcome alongside "cancelled".
        try:
            cancelled_result = await prompt_task
        except (AudiaGenticError, asyncio.CancelledError):
            cancelled_result = None
        else:
            assert cancelled_result.stop_reason in {"cancelled", "end-turn"}

        # The session itself must still be usable for a fresh turn.
        follow_up = await transport.prompt(
            SessionPrompt(
                turn_id=f"turn-{uuid.uuid4().hex[:8]}",
                body='Reply with exactly the single word: RECOVERED',
            ),
            lambda _obs: None,
        )
        assert follow_up.stop_reason == "end-turn"
        assert "RECOVERED" in (follow_up.final_summary or "")
    finally:
        await transport.close()
