"""A composer holding another tab's draft is overwritten with this prompt, never sent as is."""

from __future__ import annotations

import pytest

from audiagentic.components.providers.adapters.gpt_auto import gpt_auto_cdp as cdp


def _controller(monkeypatch, composer: dict, *, insert_fixes: bool = True):
    controller = object.__new__(cdp.GptAutoCdpBrowserController)
    controller._action_pause_seconds = 0.0
    for name in ("_PAGE_READY_PAUSE_SECONDS", "_TYPED_PAUSE_SECONDS", "_SUBMIT_POLL_SECONDS"):
        monkeypatch.setattr(cdp.GptAutoCdpBrowserController, name, 0.0)
    calls = {"insert": 0, "click": 0}

    async def evaluate(page, fn, *args):
        if fn is cdp._COMPOSER_VALIDATE_FN:
            if composer["text"] != args[0]:
                return {"validated": False, "ready": False, "clicked": False, "reason": "composer-text-mismatch"}
            return {"validated": True, "ready": True}
        if fn is cdp._COMPOSER_SELECT_ALL_FN:
            return True
        calls["click"] += 1
        return composer["text"] == args[0]

    async def insert_text(page, text):
        calls["insert"] += 1
        if insert_fixes or calls["insert"] > 1:
            composer["text"] = text

    controller.evaluate = evaluate
    controller.insert_text = insert_text
    return controller, calls


@pytest.mark.asyncio
async def test_foreign_draft_is_replaced_then_sent(monkeypatch):
    composer = {"text": "another request's prompt"}
    controller, calls = _controller(monkeypatch, composer, insert_fixes=False)
    result = await controller.submit(object(), "my prompt", timeout=5.0)
    assert composer["text"] == "my prompt"
    assert calls["insert"] >= 2  # initial insert was overwritten; re-insert fixed it
    assert calls["click"] == 1
    assert result is not None


@pytest.mark.asyncio
async def test_foreign_draft_never_sent_when_it_cannot_be_replaced(monkeypatch):
    composer = {"text": "another request's prompt"}
    controller, calls = _controller(monkeypatch, composer)

    async def stuck_insert(page, text):
        calls["insert"] += 1  # draft sync keeps restoring the foreign text

    controller.insert_text = stuck_insert
    with pytest.raises(TimeoutError):
        await controller.submit(object(), "my prompt", timeout=1.0)
    assert calls["click"] == 0
    assert calls["insert"] == 1 + cdp.GptAutoCdpBrowserController._MAX_COMPOSER_REINSERTS


class _Page:
    def __init__(self, url: str) -> None:
        self.url = url


@pytest.mark.asyncio
async def test_prompt_initiation_is_serial_across_projects(monkeypatch):
    import asyncio

    controller, _ = _controller(monkeypatch, {"text": "x"})
    state = {"active": 0, "peak": 0}

    async def fake_serialized(page, text, *, timeout=None, stage_callback=None):
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        await asyncio.sleep(0.03)
        state["active"] -= 1
        return {"actionComplete": True}

    controller._submit_serialized = fake_serialized
    one = "https://chatgpt.com/g/g-p-example-one/project"
    two = "https://chatgpt.com/g/g-p-example-two/project"
    await asyncio.gather(
        controller.submit(_Page(one), "a"),
        controller.submit(_Page(one), "b"),
        controller.submit(_Page(two), "c"),
    )
    assert state["peak"] == 1  # never two initiations at once, in any project


@pytest.mark.asyncio
async def test_timeout_reports_why_the_send_gate_never_opened(monkeypatch):
    composer = {"text": "another request's prompt"}
    controller, _ = _controller(monkeypatch, composer)

    async def stuck_insert(page, text):
        pass

    controller.insert_text = stuck_insert
    with pytest.raises(cdp.ComposerSubmissionTimeout) as caught:
        await controller.submit(object(), "my prompt", timeout=0.5)
    assert caught.value.gate_reason == "composer-text-mismatch"
    assert caught.value.send_attempted is False
