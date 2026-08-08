/**
 * Test: waitForSelector replaces is_generating polling for generation start/stop.
 *
 * Replaces the await is_generating(client) calls in _poll_response() that check
 * for the stop button / streaming indicators via polling.  Instead we use
 * waitForSelector to detect when generation starts, and waitForFunction
 * to detect when it stops (selector disappeared).
 *
 * Prerequisites: Chrome/Edge open with --remote-debugging-port=9222, logged into ChatGPT.
 *
 *     node tests/gpt_auto/test_wait_for_selector.js
 */

const puppeteer = require("puppeteer-core");

const STOP_SELECTOR = '[data-testid="stop-generating"]';

async function main() {
	let browser, page;
	let passed = 0;
	let failed = 0;

	try {
		console.log("→ Connecting to Chrome via CDP (port 9222)…");
		browser = await puppeteer.connect({
			browserURL: "http://127.0.0.1:9222",
			defaultViewport: null,
		});

		const pages = await browser.pages();
		for (const p of pages) {
			if (p.url().includes("chatgpt.com")) {
				page = p;
				break;
			}
		}

		if (!page) {
			console.log("→ No ChatGPT tab found — opening one…");
			page = await browser.newPage();
			await page.goto("https://chatgpt.com", {
				waitUntil: "networkidle2",
				timeout: 60000,
			});
		}

		console.log(`→ Active tab: ${page.url()}\n`);

		// ── Test 1: stop button NOT present (no generation) ─────────────
		console.log("━━━ Test 1: stop button absent (no active generation)");
		try {
			await page.waitForSelector(STOP_SELECTOR, { timeout: 2000 });
			console.log("  FAIL — stop button found when no generation is active");
			failed++;
		} catch (e) {
			// Timeout expected — no stop button when not generating
			console.log("  PASS — correctly timed out (no generation active)");
			passed++;
		}

		// ── Test 2: waitForFunction for "not generating" ────────────────
		console.log("\n━━━ Test 2: waitForFunction detects 'not generating' state");
		try {
			const start = Date.now();
			await page.waitForFunction(
				"() => !document.querySelector('[data-testid=\"stop-generating\"]')",
				{ timeout: 5000 },
			);
			const elapsed = (Date.now() - start) / 1000;
			if (elapsed < 1.0) {
				console.log(
					`  PASS — 'not generating' detected in ${elapsed.toFixed(2)}s`,
				);
				passed++;
			} else {
				console.log(`  WARN — detected but slow (${elapsed.toFixed(2)}s)`);
				passed++;
			}
		} catch (e) {
			console.log(
				`  FAIL — did not detect 'not generating' within 5s: ${e.message}`,
			);
			failed++;
		}

		// ── Test 3: synthetic stop button appears ───────────────────────
		console.log("\n━━━ Test 3: waitForSelector detects stop button appearing");
		await page.evaluate(() => {
			const btn = document.createElement("div");
			btn.setAttribute("data-testid", "stop-generating");
			btn.id = "test-stop-btn";
			document.body.appendChild(btn);
		});

		try {
			const start = Date.now();
			await page.waitForSelector(STOP_SELECTOR, { timeout: 3000 });
			const elapsed = (Date.now() - start) / 1000;
			console.log(
				`  PASS — detected stop button in ${elapsed.toFixed(2)}s (event-based)`,
			);
			passed++;
		} catch (e) {
			console.log(`  FAIL — did not detect injected stop button: ${e.message}`);
			failed++;
		}

		// ── Test 4: waitForFunction detects stop button disappearing ────
		console.log(
			"\n━━━ Test 4: waitForFunction detects stop button disappearing",
		);
		const removePromise = new Promise(async (resolve) => {
			setTimeout(() => {
				page
					.evaluate(() => {
						const el = document.getElementById("test-stop-btn");
						if (el) el.remove();
					})
					.then(resolve);
			}, 500);
		});

		try {
			const start = Date.now();
			await Promise.all([
				removePromise,
				page.waitForFunction(
					"() => !document.querySelector('[data-testid=\"stop-generating\"]')",
					{ timeout: 5000 },
				),
			]);
			const elapsed = (Date.now() - start) / 1000;
			console.log(
				`  PASS — stop button disappearance detected in ${elapsed.toFixed(2)}s`,
			);
			passed++;
		} catch (e) {
			console.log(
				`  FAIL — did not detect stop button disappearing: ${e.message}`,
			);
			failed++;
		}

		// ── Test 5: full generation cycle ───────────────────────────────
		console.log("\n━━━ Test 5: full generation cycle (start → run → stop)");
		await page.evaluate(() => {
			const btn = document.createElement("div");
			btn.setAttribute("data-testid", "stop-generating");
			btn.id = "test-stop-btn-2";
			document.body.appendChild(btn);
		});

		try {
			const start = Date.now();
			await page.waitForSelector(STOP_SELECTOR, { timeout: 3000 });
			const t1 = (Date.now() - start) / 1000;
			console.log(`  Phase 1 (generation started): ${t1.toFixed(2)}s`);

			const stopPromise = new Promise(async (resolve) => {
				setTimeout(() => {
					page
						.evaluate(() => {
							const el = document.getElementById("test-stop-btn-2");
							if (el) el.remove();
						})
						.then(resolve);
				}, 500);
			});

			await Promise.all([
				stopPromise,
				page.waitForFunction(
					"() => !document.querySelector('[data-testid=\"stop-generating\"]')",
					{ timeout: 5000 },
				),
			]);
			const t2 = (Date.now() - start) / 1000;
			console.log(`  Phase 2 (generation stopped): ${t2.toFixed(2)}s`);
			console.log(`  PASS — full cycle detected in ${t2.toFixed(2)}s total`);
			passed++;
		} catch (e) {
			console.log(`  FAIL — ${e.message}`);
			failed++;
		}

		// ── Test 6: ProseMirror via waitForSelector ─────────────────────
		console.log("\n━━━ Test 6: waitForSelector for .ProseMirror editor");
		try {
			// Find a chat page with the editor (not /projects)
			const allPages = await browser.pages();
			const chatPage = allPages.find(
				(p) =>
					p.url().includes("chatgpt.com") && !p.url().includes("/projects"),
			);
			let targetPage = chatPage || page;

			// If only on /projects, navigate to home first
			if (!chatPage) {
				await page.goto("https://chatgpt.com", {
					waitUntil: "networkidle2",
					timeout: 30000,
				});
				targetPage = page;
			}

			const start = Date.now();
			await targetPage.waitForSelector(".ProseMirror", { timeout: 15000 });
			const elapsed = (Date.now() - start) / 1000;
			console.log(`  PASS — .ProseMirror found in ${elapsed.toFixed(2)}s`);
			passed++;
		} catch (e) {
			console.log(`  FAIL — did not find .ProseMirror: ${e.message}`);
			failed++;
		}

		// ── Test 7: combined ready check via waitForFunction ────────────
		console.log("\n━━━ Test 7: combined ready check via waitForFunction");
		try {
			const allPages2 = await browser.pages();
			const chatPage2 = allPages2.find(
				(p) =>
					p.url().includes("chatgpt.com") && !p.url().includes("/projects"),
			);
			let targetPage2 = chatPage2 || page;

			if (!chatPage2) {
				await page.goto("https://chatgpt.com", {
					waitUntil: "networkidle2",
					timeout: 30000,
				});
				targetPage2 = page;
			}

			const start = Date.now();
			await targetPage2.waitForFunction(
				() => {
					const editor = document.querySelector(".ProseMirror");
					if (!editor) return false;
					const loginBtns = document.querySelector(
						'[data-testid="login-button"], [data-testid="signup-button"]',
					);
					return !loginBtns;
				},
				{ timeout: 15000 },
			);
			const elapsed = (Date.now() - start) / 1000;
			console.log(`  PASS — combined ready check in ${elapsed.toFixed(2)}s`);
			passed++;
		} catch (e) {
			console.log(`  FAIL — combined ready check: ${e.message}`);
			failed++;
		}

		// ── Summary ───────────────────────────────────────────────────
		console.log("\n" + "=".repeat(60));
		console.log(`Tests passed: ${passed}/${passed + failed}`);
		if (failed > 0) {
			console.log(`Tests failed: ${failed}`);
			process.exitCode = 1;
		}
	} finally {
		if (browser) browser.disconnect();
	}
}

main().catch((e) => {
	console.error("Fatal:", e);
	process.exit(1);
});
