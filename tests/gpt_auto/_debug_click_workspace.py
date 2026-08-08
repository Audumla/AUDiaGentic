"""Debug: click workspace via CDP mouse events."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from audiagentic.components.providers.adapters.gpt_auto.cdp_client import CdpClient


async def main():
    c = CdpClient(cdp_url="http://127.0.0.1:9222")
    await c.start()
    tabs = await c.list_tabs()

    for t in tabs:
        if "chatgpt.com" in t.url:
            r = await c.activate_tab(t.tab_id)
            if not r:
                continue

            print("Navigating to /projects...")
            await c.evaluate("() => window.location.href = 'https://chatgpt.com/projects'")
            await asyncio.sleep(3.0)

            # Get the bounding rect of the AUDiaGentic menu item
            name = "AUDiaGentic"
            rect = await c.evaluate(
                """(name) => {
                    const target = name.toLowerCase();
                    const rows = document.querySelectorAll('[class*="project-unfurl-row"]');
                    for (let i = 0; i < rows.length; i++) {
                        const text = (rows[i].textContent || '').trim().toLowerCase();
                        if (text.includes(target)) {
                            const menuItem = rows[i].querySelector('[tabindex="0"]');
                            if (!menuItem) return null;
                            const rect = menuItem.getBoundingClientRect();
                            return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, w: rect.width, h: rect.height };
                        }
                    }
                    return null;
                }""",
                name,
            )
            if not rect:
                print("Not found")
                break

            print(f"Menu item rect: x={rect['x']}, y={rect['y']}, w={rect['w']}, h={rect['h']}")

            # Use puppeteer directly for a real click (CDP client doesn't expose Input.dispatchMouseEvent)
            print("Using puppeteer for real click...")
            result = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    "node",
                    "-e",
                    f"const puppeteer = require('puppeteer-core');(async()=>{{const b=await puppeteer.connect({{browserURL:'http://127.0.0.1:9222',defaultViewport:null}});for(const p of await b.pages()){{if(p.url().includes('chatgpt.com')){{try{{await p.goto('https://chatgpt.com/projects');await new Promise(r=>setTimeout(r,3000));const els=await p.$('[class*=project-unfurl-row]');const rows=await p.$$('[class*=project-unfurl-row]');for(const r of rows){{const t=await r.evaluate(el=>el.textContent.trim());if(t.toLowerCase().includes('{name}'.toLowerCase())){{const btn=await r.$('[tabindex=0]');if(btn){{await btn.click();break;}}}}}}await new Promise(r=>setTimeout(r,5000));console.log(p.url());}}catch(e){{console.error(e);}}break;}}b.disconnect();}})().catch(e=>console.error(e))",
                    env={**dict(os.environ), "NODE_PATH": "C:\\Users\\mgs\\.audiagentic\\providers\\gpt-auto\\npm\\node_modules"},
                ),
                timeout=30,
            )
            stdout = await result.stdout.read()
            print(f"Puppeteer result: {stdout.decode()}".strip())
            print("Clicked via CDP mouse event")

            # Wait for navigation
            await asyncio.sleep(5.0)

            # Check current URL
            url = await c.evaluate("() => window.location.href")
            print(f"Current URL after click: {url}")

            # Check if we have an editor
            try:
                ready = await c.evaluate(
                    "() => { const e = document.querySelector('.ProseMirror'); return !!e; }"
                )
                print(f"Editor present: {ready}")
            except Exception as e:
                print(f"Error checking editor: {e}")

            break

    await c.stop()

if __name__ == "__main__":
    asyncio.run(main())
