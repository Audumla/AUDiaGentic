"""Continuous DOM monitor for diagnosing gpt-auto turn-completion detection.

Runs as a standalone observer alongside a live gpt-auto turn and samples the
ChatGPT DOM every interval, recording *which specific element* satisfies each
``is_generating()`` sub-check.  The production predicate only returns a single
boolean, so when a turn appears to hang there is no way to tell which of its
several heuristics is stuck true.  This tool answers that.

Deliberately passive: it uses ``activate_tab`` (which only sets the helper's
page pointer) and never calls ``bring_to_front``, so it cannot steal focus
from the tab the real session is driving.

    python tests/gpt_auto/_debug_dom_monitor.py [--seconds 1800] [--interval 2]

Writes JSONL samples to ``dom_monitor_<timestamp>.jsonl`` and prints a compact
line per state change.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from audiagentic.components.providers.adapters.gpt_auto.cdp_client import CdpClient

# Mirrors the production _IS_GENERATING_JS checks, but reports *which* element
# matched each one, plus whether that element is actually visible.  A hidden
# element matching a broad substring selector (e.g. [class*="loading"]) would
# make the production predicate stick true forever while the user sees a
# finished answer -- exactly the failure being diagnosed.
_PROBE_JS = r"""() => {
    const describe = (el) => {
        if (!el) return null;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return {
            tag: el.tagName,
            cls: (typeof el.className === 'string' ? el.className : '').slice(0, 120),
            testid: el.getAttribute('data-testid') || null,
            label: (el.getAttribute('aria-label') || '').slice(0, 60) || null,
            w: Math.round(rect.width),
            h: Math.round(rect.height),
            visible: rect.width > 0 && rect.height > 0
                && style.display !== 'none' && style.visibility !== 'hidden'
                && style.opacity !== '0',
        };
    };

    // 1. stop-generating testid
    const stopBtn = document.querySelector('[data-testid="stop-generating"]');

    // 2. loader/streaming/thinking classes
    const loaderSel = '.loading-dots, [class*="streaming"], .result-streaming, .result-thinking, [class*="result-thinking"]';
    const loaderEls = Array.from(document.querySelectorAll(loaderSel));

    // 3. any button whose aria-label mentions "stop"
    const stopLabelled = Array.from(document.querySelectorAll('button, [role="button"]'))
        .filter(b => (b.getAttribute('aria-label') || '').toLowerCase().includes('stop'));

    // 4. page-level busy indicators
    const busySelectors = ['[class*="spinner"]','[class*="loading"]','[aria-busy="true"]','[data-busy="true"]','[class*="busy"]'];
    const busyHits = [];
    for (const sel of busySelectors) {
        const el = document.querySelector(sel);
        if (el) busyHits.push({ sel, el: describe(el) });
    }

    // 5. editor editability
    const editor = document.querySelector('.ProseMirror');
    const editorState = editor ? {
        contentEditable: editor.isContentEditable,
        disabled: editor.hasAttribute('disabled'),
        attr: editor.getAttribute('contenteditable'),
    } : null;

    // Composer buttons -- candidate alternative completion signals.
    const composerBtns = Array.from(document.querySelectorAll('button[data-testid], [role="button"][data-testid]'))
        .map(b => ({
            testid: b.getAttribute('data-testid'),
            label: (b.getAttribute('aria-label') || '').slice(0, 60) || null,
            disabled: b.hasAttribute('disabled') || b.getAttribute('aria-disabled') === 'true',
        }))
        .filter(b => /send|stop|speech|voice|compose|submit/i.test(b.testid || ''));

    // Assistant response state (same logic as production _GET_RESPONSE_STATE_JS)
    const blocks = document.querySelectorAll('[data-message-author-role="assistant"]');
    const real = Array.from(blocks).filter(b => !(b.getAttribute('data-message-id') || '').startsWith('request-placeholder-request-'));
    const lastText = real.length ? (real[real.length - 1].innerText || '').trim() : null;

    // The production predicate's own verdict, recomputed here.
    const generating = !!stopBtn
        || loaderEls.length > 0
        || stopLabelled.length > 0
        || busyHits.length > 0
        || (editor && (!editor.isContentEditable || editor.hasAttribute('disabled') || !editor.getAttribute('contenteditable')));

    return {
        generating: !!generating,
        stopBtn: describe(stopBtn),
        loaders: loaderEls.slice(0, 4).map(describe),
        loaderCount: loaderEls.length,
        stopLabelled: stopLabelled.slice(0, 4).map(describe),
        busyHits,
        editorState,
        composerBtns,
        blockCount: real.length,
        textLen: lastText ? lastText.length : 0,
        textTail: lastText ? lastText.slice(-80) : null,
    };
}"""


def _digest(text: str | None) -> str:
    if not text:
        return "-"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _reason(sample: dict) -> str:
    """Human-readable summary of *why* generating is currently true."""
    reasons = []
    if sample.get("stopBtn"):
        vis = "visible" if sample["stopBtn"].get("visible") else "HIDDEN"
        reasons.append(f"stopBtn({vis},label={sample['stopBtn'].get('label')})")
    if sample.get("loaderCount"):
        first = (sample.get("loaders") or [None])[0]
        if first:
            vis = "visible" if first.get("visible") else "HIDDEN"
            reasons.append(f"loaders x{sample['loaderCount']}({vis},cls={first.get('cls')[:40]})")
        else:
            reasons.append(f"loaders x{sample['loaderCount']}")
    if sample.get("stopLabelled"):
        first = sample["stopLabelled"][0]
        vis = "visible" if first.get("visible") else "HIDDEN"
        reasons.append(f"stopLabel({vis},{first.get('label')})")
    for hit in sample.get("busyHits") or []:
        el = hit.get("el") or {}
        vis = "visible" if el.get("visible") else "HIDDEN"
        reasons.append(f"busy[{hit['sel']}]({vis},cls={(el.get('cls') or '')[:40]})")
    ed = sample.get("editorState")
    if ed and (not ed.get("contentEditable") or ed.get("disabled") or not ed.get("attr")):
        reasons.append(f"editorBlocked({ed})")
    return "; ".join(reasons) if reasons else "-"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=1800.0, help="max monitor duration")
    ap.add_argument("--interval", type=float, default=2.0, help="sample interval")
    ap.add_argument("--out", type=str, default="", help="JSONL output path")
    args = ap.parse_args()

    out_path = Path(args.out) if args.out else Path(f"dom_monitor_{int(time.time())}.jsonl")

    client = CdpClient(cdp_url="http://127.0.0.1:9222")
    await client.start()

    tabs = await client.list_tabs()
    target = None
    for t in tabs:
        if "chatgpt.com" in t.url.lower() and "/c/" in t.url.lower():
            target = t
            break
    if target is None:
        for t in tabs:
            if "chatgpt.com" in t.url.lower():
                target = t
                break
    if target is None:
        print("No ChatGPT tab found")
        await client.stop()
        return 1

    # Passive: sets the helper's page pointer only, never bring_to_front.
    await client.activate_tab(target.tab_id)
    print(f"Monitoring: {target.url}")
    print(f"Writing:    {out_path}")
    print(f"{'elapsed':>8} {'gen':>5} {'blk':>4} {'len':>7} {'hash':>9}  reason")

    started = time.monotonic()
    prev_key: tuple | None = None
    n = 0

    with out_path.open("w", encoding="utf-8") as fh:
        while time.monotonic() - started < args.seconds:
            elapsed = time.monotonic() - started
            try:
                sample = await client.evaluate(_PROBE_JS)
            except Exception as exc:  # noqa: BLE001 -- diagnostic must not die
                sample = {"error": str(exc)[:200]}

            n += 1
            record = {"t": round(elapsed, 1), "n": n, **(sample or {})}
            fh.write(json.dumps(record) + "\n")
            fh.flush()

            if isinstance(sample, dict) and "error" not in sample:
                reason = _reason(sample)
                key = (
                    sample.get("generating"),
                    sample.get("blockCount"),
                    sample.get("textLen"),
                    reason,
                )
                if key != prev_key:
                    print(
                        f"{elapsed:8.1f} {str(sample.get('generating')):>5} "
                        f"{sample.get('blockCount'):>4} {sample.get('textLen'):>7} "
                        f"{_digest(sample.get('textTail')):>9}  {reason}"
                    )
                    prev_key = key
            else:
                print(f"{elapsed:8.1f}  ERROR {sample}")

            await asyncio.sleep(args.interval)

    await client.stop()
    print(f"\nDone. {n} samples -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
