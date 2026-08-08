"""Quick demo — type a prompt into ChatGPT so you can SEE it happen."""

import asyncio
import time

from audiagentic.components.providers.adapters.gpt_auto.cdp_client import CdpClient


async def main():
    c = CdpClient(cdp_url="http://127.0.0.1:9222")
    await c.start()
    tabs = await c.list_tabs()

    for t in tabs:
        if "chatgpt.com" in t.url and "/projects" not in t.url:
            r = await c.activate_tab(t.tab_id)
            if not r:
                print(f"FAIL — could not activate tab {t.tab_id}")
                continue
            print(f"Activated tab: {r.url}")

            # Ready check
            t0 = time.monotonic()
            ready = await c.evaluate(
                "() => { const e = document.querySelector('.ProseMirror'); "
                "if (!e) return false; "
                "const t = (document.body.textContent || ''); "
                "return !t.includes('Sign in') && !t.includes('Log in'); }"
            )
            print(f"[1] Ready: {ready} ({time.monotonic() - t0:.2f}s)")

            # Clear editor
            await c.evaluate(
                "() => { const e = document.querySelector('.ProseMirror'); if (e) { e.innerHTML = ''; e.focus(); } }"
            )
            print("[2] Editor cleared")

            # Type text — 50ms per keystroke so you can SEE it
            text = "What is 7 times 3?"
            for ch in text:
                await c.evaluate(
                    "(ch) => { const e = document.querySelector('.ProseMirror'); if (e) e.textContent += ch; }",
                    ch,
                )
                await asyncio.sleep(0.05)
            print(f'[3] Typed: "{text}"')

            # Submit
            result = await c.evaluate(
                "() => { "
                "const e = document.querySelector('.ProseMirror'); "
                "if (!e) return { error: 'no editor' }; "
                "const btns = document.querySelectorAll('button, [role=\"button\"]'); "
                "for (const b of btns) { "
                "  const l = (b.getAttribute('aria-label') || '').toLowerCase(); "
                "  if (l.includes('send') || l.includes('submit')) { b.click(); return { ok: true, label: b.getAttribute('aria-label') }; } "
                "} "
                "return { submitted: false }; }"
            )
            print(f"[4] Submit: {result}")

            # Wait for response
            print("[5] Waiting for response...")
            for i in range(30):
                count, txt = await c.evaluate(
                    "() => { "
                    "const blocks = document.querySelectorAll('[data-message-author-role=\"assistant\"]'); "
                    "const real = Array.from(blocks).filter(b => !b.getAttribute('data-message-id', '').startsWith('request-placeholder-request-')); "
                    "if (real.length === 0) return [0, null]; "
                    "const last = real[real.length - 1]; "
                    "return [real.length, (last.innerText || '').trim()]; }"
                )
                if count > 0 and txt:
                    print(f"   Response ({count} blocks): {txt[:200]!r}")
                    break
                await asyncio.sleep(1.0)
                if i % 5 == 4:
                    print(f"   ... waiting ({i + 1}s)")

            # Generation state
            gen = await c.evaluate(
                "() => !!document.querySelector('[data-testid=\"stop-generating\"]')"
            )
            print(f"[6] Generating: {gen}")

            # Only run demo on one tab
            break

    await c.stop()
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
