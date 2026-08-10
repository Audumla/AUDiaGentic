"use strict";

const puppeteer = require("puppeteer-core");

let browser = null;
let page = null;

function respond(id, result) {
	process.stdout.write(JSON.stringify({ id, result }) + "\n");
}

function error(id, message) {
	process.stdout.write(JSON.stringify({ id, error: message }) + "\n");
}

async function handle(msg) {
	const id = msg.id;
	try {
		switch (msg.method) {
			case "connect": {
				// browserURL makes puppeteer GET /json/version to discover the
				// websocket URL, which Chromium 404s on a default-profile
				// browser even though the CDP socket itself is fine. The
				// browser writes that same websocket path to
				// DevToolsActivePort, so fall back to it.
				//
				// The real connect is the probe: an HTTP pre-check in Python
				// would race the connect that follows it (the endpoint can
				// change or be incomplete in between).
				try {
					browser = await puppeteer.connect({
						browserURL:
							msg.params.browserURL || "http://127.0.0.1:9222",
						defaultViewport: null,
					});
				} catch (err) {
					if (!msg.params.browserWSEndpoint) throw err;
					browser = await puppeteer.connect({
						browserWSEndpoint: msg.params.browserWSEndpoint,
						defaultViewport: null,
					});
				}
				respond(id, { ok: true });
				break;
			}
			case "new_tab": {
				if (!browser) return error(id, "Not connected");
				page = await browser.newPage();
				const url = msg.params.url || "https://chatgpt.com";
				await page.goto(url, { waitUntil: "networkidle2", timeout: 60000 });
				respond(id, {
					ok: true,
					url: page.url(),
					tabId: page.target()._targetId,
				});
				break;
			}
			case "find_tab": {
				if (!browser) return error(id, "Not connected");
				for (const p of await browser.pages()) {
					const url = p.url();
					const title = await p.title().catch(() => "");
					if (
						(msg.params.urlPattern && url.includes(msg.params.urlPattern)) ||
						(msg.params.titlePattern && title.includes(msg.params.titlePattern))
					) {
						page = p;
						respond(id, {
							found: true,
							url,
							title,
							tabId: p.target()._targetId,
						});
						return;
					}
				}
				respond(id, { found: false });
				break;
			}
			case "list_tabs": {
				if (!browser) return error(id, "Not connected");
				const tabs = [];
				for (const p of await browser.pages()) {
					tabs.push({
						tabId: p.target()._targetId,
						url: p.url(),
						title: await p.title().catch(() => ""),
					});
				}
				respond(id, { tabs });
				break;
			}
			case "activate_tab": {
				if (!browser) return error(id, "Not connected");
				for (const p of await browser.pages()) {
					if (p.target()._targetId === msg.params.tabId) {
						page = p;
						respond(id, {
							found: true,
							url: p.url(),
							tabId: p.target()._targetId,
						});
						return;
					}
				}
				respond(id, { found: false });
				break;
			}
			case "bring_to_front": {
				if (!page) return error(id, "No active page");
				// Focus the tab in the browser (Chrome foregrounds the window and
				// tab).  Without this, a backgrounded ChatGPT tab pauses SSE
				// streaming and the response never grows past its first chunk.
				try {
					await page.bringToFront();
				} catch (e) {
					/* best-effort */
				}
				try {
					await page.focus();
				} catch (e) {
					/* best-effort */
				}
				await new Promise((r) => setTimeout(r, 250));
				respond(id, { ok: true, url: page.url() });
				break;
			}
			case "keep_page_active": {
				// Make the page behave as focused+visible even when its window
				// is occluded or backgrounded.
				//
				// Verified failure this fixes (2026-08-09): with the browser
				// behind another window, ChatGPT's SSE stream aborts after the
				// first chunk -- the assistant block freezes at ~10 characters
				// with streaming-animation still applied and the stop button
				// gone, indefinitely. bringToFront() before injecting is not
				// enough because occlusion happens *during* the response.
				//
				// Emulation.setFocusEmulationEnabled makes the renderer report
				// the page as focused/active, and Page.setWebLifecycleState
				// keeps it out of the frozen/throttled lifecycle state --
				// neither steals focus from whatever the user is actually
				// doing, unlike bringToFront().
				if (!page) return error(id, "No active page");
				const applied = [];
				const failed = [];
				try {
					const session = await page.createCDPSession();
					try {
						await session.send("Emulation.setFocusEmulationEnabled", {
							enabled: true,
						});
						applied.push("focus-emulation");
					} catch (e) {
						failed.push("focus-emulation: " + String(e && e.message).slice(0, 120));
					}
					try {
						await session.send("Page.setWebLifecycleState", {
							state: "active",
						});
						applied.push("web-lifecycle-active");
					} catch (e) {
						failed.push("web-lifecycle: " + String(e && e.message).slice(0, 120));
					}
				} catch (e) {
					failed.push("cdp-session: " + String(e && e.message).slice(0, 120));
				}
				respond(id, { ok: applied.length > 0, applied, failed });
				break;
			}
			case "click": {
				if (!page) return error(id, "No active page");
				const el = await page.$(msg.params.selector);
				if (!el) return error(id, `Element not found: ${msg.params.selector}`);
				await el.click();
				respond(id, { ok: true });
				break;
			}
			case "type_text": {
				if (!page) return error(id, "No active page");
				const delay = msg.params.delay || 30;
				for (const ch of msg.params.text) {
					await page.keyboard.type(ch);
					await new Promise((r) => setTimeout(r, delay));
				}
				respond(id, { ok: true });
				break;
			}
			case "press_key": {
				if (!page) return error(id, "No active page");
				await page.keyboard.press(msg.params.key);
				respond(id, { ok: true });
				break;
			}
			case "evaluate": {
				if (!page) return error(id, "No active page");
				let script = msg.params.script;
				const args = msg.params.args;

				let result;
				try {
					if (args && args.length > 0) {
						// Puppeteer can't serialize function strings + args across CDP.
						// Store args on window, then evaluate. Script should access via
						// _cdpArgs[0], _cdpArgs[1], etc.
						const argJson = JSON.stringify(args);
						const preamble = `window._cdpArgs=${argJson};`;
						result = await page.evaluate(preamble + script);
					} else {
						// Wrap bare arrow functions in IIFE — puppeteer returns {} for "() => ...".
						if (!script.startsWith("(()") && !script.startsWith("(function")) {
							script = `(${script})()`;
						}
						result = await page.evaluate(script);
					}
				} catch (e) {
					return error(id, `evaluate: ${e.message}`);
				}
				respond(id, { value: result });
				break;
			}
			case "screenshot": {
				if (!page) return error(id, "No active page");
				await page.screenshot({ path: msg.params.path });
				respond(id, { ok: true });
				break;
			}
			case "click_js": {
				if (!page) return error(id, "No active page");
				const elHandle = await page.evaluateHandle(msg.params.js);
				const el = elHandle.asElement();
				if (!el) return error(id, "Element not found by JS query");

				// Try multiple click strategies for React elements
				try {
					await el.click({ force: true });
				} catch (e1) {
					// Fallback: dispatch native click event via CDP
					const rect = await page.evaluate(
						(h) => h.getBoundingClientRect(),
						elHandle,
					);
					if (rect.width > 0 && rect.height > 0) {
						await page.mouse.click(
							Math.round(rect.x + rect.width / 2),
							Math.round(rect.y + rect.height / 2),
						);
					}
				}

				respond(id, { ok: true });
				break;
			}
			case "mouse_click": {
				if (!page) return error(id, "No active page");
				const x = msg.params.x;
				const y = msg.params.y;
				await page.mouse.click(x, y);
				respond(id, { ok: true });
				break;
			}
			case "wait_for_function": {
				if (!page) return error(id, "No active page");
				const predicate = msg.params.predicate || "() => true";
				const timeoutMs = msg.params.timeoutMs || 30000;
				try {
					await page.waitForFunction(predicate, { timeout: timeoutMs });
					respond(id, { ok: true });
				} catch (e) {
					return error(id, `waitForFunction: ${e.message}`);
				}
				break;
			}
			case "wait_for_selector": {
				if (!page) return error(id, "No active page");
				const selector = msg.params.selector;
				const timeoutMs = msg.params.timeoutMs || 30000;
				try {
					await page.waitForSelector(selector, { timeout: timeoutMs });
					respond(id, { ok: true });
				} catch (e) {
					return error(id, `waitForSelector: ${e.message}`);
				}
				break;
			}
			case "get_url": {
				if (!page) return error(id, "No active page");
				respond(id, { url: page.url() });
				break;
			}
			case "disconnect": {
				if (browser) {
					browser.disconnect();
					browser = null;
					page = null;
				}
				respond(id, { ok: true });
				break;
			}
			default:
				error(id, `Unknown method: ${msg.method}`);
		}
	} catch (e) {
		error(id, e.message);
	}
}

const reqId = 0;
process.stdin.setEncoding("utf8");
let buf = "";
process.stdin.on("data", (chunk) => {
	buf += chunk;
	let nl;
	while ((nl = buf.indexOf("\n")) !== -1) {
		const line = buf.slice(0, nl).trim();
		buf = buf.slice(nl + 1);
		if (!line) continue;
		try {
			handle(JSON.parse(line));
		} catch (e) {
			/* skip */
		}
	}
});
process.stdin.on("end", () => {
	if (browser) browser.disconnect();
	process.exit(0);
});

// Signal ready on stderr so Python knows we're alive
process.stderr.write("gpt-auto-cdp ready\n");
