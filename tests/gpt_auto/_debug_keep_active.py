"""Hold CDP focus/visibility emulation on the ChatGPT tab.

ChatGPT aborts an in-flight SSE response after its first chunk once the tab
becomes hidden or occluded -- the assistant block freezes part-written and the
turn never completes (observed 2026-08-09: stuck at 10 characters for 15+
minutes with ``streaming-animation`` still applied).

``Emulation.setFocusEmulationEnabled`` + ``Page.setWebLifecycleState`` make the
renderer report itself focused and visible, so streaming continues while the
window sits behind the user's editor. Both are scoped to the CDP session that
set them and reset on disconnect, so this process stays connected until
interrupted.

Production does not need this script -- ``GptAutoSessionTransport`` applies the
same emulation on its own long-lived client. This exists to hold emulation for
a session driven by a process that predates that fix, and to verify the
behaviour interactively.

    python tests/gpt_auto/_debug_keep_active.py [--seconds 3600]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from audiagentic.components.providers.adapters.gpt_auto.cdp_client import CdpClient

_PROBE_JS = """() => ({
    hasFocus: document.hasFocus(),
    visibility: document.visibilityState,
    hidden: document.hidden,
})"""


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=3600.0)
    ap.add_argument("--interval", type=float, default=15.0)
    args = ap.parse_args()

    client = CdpClient(cdp_url="http://127.0.0.1:9222")
    await client.start()

    tabs = await client.list_tabs()
    target = next(
        (t for t in tabs if "chatgpt.com" in t.url.lower() and "/c/" in t.url.lower()), None
    ) or next((t for t in tabs if "chatgpt.com" in t.url.lower()), None)
    if target is None:
        print("No ChatGPT tab found")
        await client.stop()
        return 1

    await client.activate_tab(target.tab_id)
    result = await client.keep_page_active()
    print(f"Tab:     {target.url}")
    print(f"Applied: {result}")

    started = time.monotonic()
    last_url = target.url
    try:
        while time.monotonic() - started < args.seconds:
            probe = await client.evaluate(_PROBE_JS)
            url = await client.get_url()

            # A navigation swaps the renderer, which drops the emulation --
            # re-apply so the first turn (workspace-root -> /c/{id}) does not
            # silently lose it.
            if url != last_url:
                await client.keep_page_active()
                print(f"[{time.monotonic() - started:7.1f}s] navigated -> re-applied ({url})")
                last_url = url
            elif not (probe or {}).get("hasFocus"):
                await client.keep_page_active()
                print(f"[{time.monotonic() - started:7.1f}s] emulation lapsed -> re-applied")

            await asyncio.sleep(args.interval)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await client.stop()
        print("Released emulation")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
