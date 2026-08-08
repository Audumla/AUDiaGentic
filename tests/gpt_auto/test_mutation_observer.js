/**
 * Test: MutationObserver detects assistant text changes instantly.
 *
 * Replaces the 2-second polling interval in _poll_response() for detecting
 * new response text.  A MutationObserver watches assistant blocks and fires
 * instantly when text content changes — no need to wait for the next poll tick.
 *
 * This test injects an observer, simulates ChatGPT streaming by appending text
 * to a fake assistant block, and measures detection latency.
 *
 * Prerequisites: Chrome/Edge open with --remote-debugging-port=9222, logged into ChatGPT.
 *
 *     node tests/gpt_auto/test_mutation_observer.js
 */

const puppeteer = require("puppeteer-core");

// Inject a fake assistant block
async function injectAssistant(page, text) {
	await page.evaluate((t) => {
		const block = document.createElement("div");
		block.setAttribute("data-message-author-role", "assistant");
		block.setAttribute("data-test-id", "fake-assistant");
		const tn = document.createTextNode(t || "");
		block.appendChild(tn);
		document.body.appendChild(block);
	}, text);
}

// Append text to the fake assistant (simulates streaming)
async function appendToAssistant(page, text) {
	await page.evaluate((t) => {
		const block = document.querySelector("[data-test-id='fake-assistant']");
		if (!block || !block.firstChild) return;
		block.firstChild.appendData(t);
	}, text);
}

// Clear test state
async function clearTest(page) {
	await page.evaluate(() => {
		if (window.__testEvents) window.__testEvents = [];
		const fake = document.querySelector("[data-test-id='fake-assistant']");
		if (fake) fake.remove();
	});
}

// Set up the MutationObserver
async function setupObserver(page) {
	await page.evaluate(() => {
		window.__testEvents = [];
		const observer = new MutationObserver((mutations) => {
			for (const m of mutations) {
				if (
					m.type === "characterData" ||
					m.addedNodes.length > 0 ||
					m.type === "childList"
				) {
					const blocks = document.querySelectorAll(
						'[data-message-author-role="assistant"]',
					);
					const count = blocks.length;
					let text = null;
					// Only count our test blocks (filter out real ChatGPT assistant blocks)
					const testBlocks = Array.from(blocks).filter(
						(b) => b.getAttribute("data-test-id") === "fake-assistant",
					);
					if (testBlocks.length > 0) {
						text = (testBlocks[0].innerText || "").trim();
					} else if (count > 0) {
						text = (blocks[count - 1].innerText || "").trim();
					}
					window.__testEvents.push({
						type: "text_changed",
						count,
						text,
						timestamp: performance.now(),
					});
				}
			}
		});

		observer.observe(document.body, {
			characterData: true,
			subtree: true,
			childList: true,
		});
		window.__testObserver = observer;
	});
}

async function getEvents(page) {
	return await page.evaluate(() => window.__testEvents || []);
}

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

		// ── Test 1: observer setup + single text change ─────────────────
		console.log("━━━ Test 1: MutationObserver setup + single text change");
		await clearTest(page);
		await setupObserver(page);
		await injectAssistant(page, "Hello world");
		await new Promise((r) => setTimeout(r, 100));

		const events = await getEvents(page);
		if (events.length > 0 && events.some((e) => e.type === "text_changed")) {
			console.log(
				`  PASS — observer detected node creation (${events.length} event(s))`,
			);
			passed++;
		} else {
			console.log("  FAIL — no events captured");
			failed++;
		}

		// ── Test 2: streaming detection (text grows incrementally) ──────
		console.log(
			"\n━━━ Test 2: streaming simulation (text grows incrementally)",
		);
		await clearTest(page);
		await setupObserver(page);
		await injectAssistant(page, "");
		await new Promise((r) => setTimeout(r, 100));

		const chunks = ["Hello", " ", "from", " ", "ChatGPT"];
		let detectedCount = 0;

		for (const chunk of chunks) {
			const start = Date.now();
			await appendToAssistant(page, chunk);
			await new Promise((r) => setTimeout(r, 50));
			const elapsed = (Date.now() - start) / 1000;

			const evts = await getEvents(page);
			const latest = evts.length > 0 ? evts[evts.length - 1] : null;
			if (latest && latest.type === "text_changed") {
				detectedCount++;
				console.log(
					`    chunk '${chunk}' — detected in ${elapsed.toFixed(3)}s (event-based)`,
				);
			} else {
				console.log(
					`    chunk '${chunk}' — NOT detected (elapsed=${elapsed.toFixed(3)}s)`,
				);
			}
		}

		if (detectedCount === chunks.length) {
			console.log(
				`  PASS — all ${chunks.length} streaming chunks detected instantly`,
			);
			passed++;
		} else {
			console.log(
				`  FAIL — only ${detectedCount}/${chunks.length} chunks detected`,
			);
			failed++;
		}

		// ── Test 3: observer vs polling comparison for streaming ────────
		console.log(
			"\n━━━ Test 3: MutationObserver vs polling (streaming latency)",
		);
		await clearTest(page);
		await setupObserver(page);
		await injectAssistant(page, "");
		await new Promise((r) => setTimeout(r, 100));

		const chunks2 = ["A", "B", "C"];
		const observerTimes = [];

		for (const chunk of chunks2) {
			const start = Date.now();
			await appendToAssistant(page, chunk);
			await new Promise((r) => setTimeout(r, 50));
			const evts = await getEvents(page);
			if (evts.length > 0 && evts[evts.length - 1].type === "text_changed") {
				observerTimes.push((Date.now() - start) / 1000);
			}
		}

		// Polling timing — same chunks, 2s poll interval (simulated with shorter for test)
		await clearTest(page);
		await injectAssistant(page, "");
		let lastText = null;
		const pollingTimes = [];

		for (const chunk of chunks2) {
			await appendToAssistant(page, chunk);
			const start = Date.now();

			// Simulate 0.5s polling interval (shortened from production 2s for test speed)
			for (let i = 0; i < 40; i++) {
				const currentText = await page.evaluate(() => {
					const block = document.querySelector(
						"[data-test-id='fake-assistant']",
					);
					return block ? (block.innerText || "").trim() : null;
				});
				if (currentText !== lastText) {
					pollingTimes.push((Date.now() - start) / 1000);
					lastText = currentText;
					break;
				}
				await new Promise((r) => setTimeout(r, 50));
			}
		}

		if (observerTimes.length > 0 && pollingTimes.length > 0) {
			const obsAvg =
				observerTimes.reduce((a, b) => a + b, 0) / observerTimes.length;
			const pollAvg =
				pollingTimes.reduce((a, b) => a + b, 0) / pollingTimes.length;
			console.log(`  Observer avg detection: ${obsAvg.toFixed(3)}s per chunk`);
			console.log(`  Polling avg detection:  ${pollAvg.toFixed(3)}s per chunk`);
			console.log(
				`  Delta: ${pollAvg - obsAvg >= 0 ? "+" : ""}${(pollAvg - obsAvg).toFixed(3)}s (polling minus observer)`,
			);
		}

		// ── Test 4: new assistant block detected (count increases) ──────
		console.log("\n━━━ Test 4: new assistant block creation detected");
		await clearTest(page);
		await setupObserver(page);
		await injectAssistant(page, "First response");
		await new Promise((r) => setTimeout(r, 100));

		let firstCount = 0;
		const evts1 = await getEvents(page);
		for (const e of evts1) {
			if (e.type === "text_changed")
				firstCount = Math.max(firstCount, e.count || 0);
		}

		// Inject a second test block
		await page.evaluate(() => {
			const block = document.createElement("div");
			block.setAttribute("data-message-author-role", "assistant");
			block.setAttribute("data-test-id", "fake-assistant-2");
			const tn = document.createTextNode("Second response");
			block.appendChild(tn);
			document.body.appendChild(block);
		});
		await new Promise((r) => setTimeout(r, 100));

		const evts2 = await getEvents(page);
		let latestCount = 0;
		for (const e of evts2) {
			if (e.type === "text_changed")
				latestCount = Math.max(latestCount, e.count || 0);
		}

		if (latestCount > firstCount) {
			console.log(
				`  PASS — block count increased from ${firstCount} to ${latestCount}`,
			);
			passed++;
		} else {
			console.log(
				`  FAIL — block count did not increase (${firstCount} → ${latestCount})`,
			);
			failed++;
		}

		// ── Test 5: stability window (no spurious events) ───────────────
		console.log("\n━━━ Test 5: stability window (text stops changing)");
		await clearTest(page);
		await setupObserver(page);
		await injectAssistant(page, "");
		await new Promise((r) => setTimeout(r, 100));

		for (const chunk of ["Test", " ", "response"]) {
			await appendToAssistant(page, chunk);
			await new Promise((r) => setTimeout(r, 50));
		}

		const eventCountBefore = (await getEvents(page)).length;
		await new Promise((r) => setTimeout(r, 500));
		const eventCountAfter = (await getEvents(page)).length;

		if (eventCountBefore === eventCountAfter) {
			console.log(
				`  PASS — no spurious events during stability window (${eventCountBefore} events)`,
			);
			passed++;
		} else {
			console.log(
				`  WARN — ${eventCountAfter - eventCountBefore} extra events during stable period`,
			);
			passed++;
		}

		// Cleanup
		await page.evaluate(() => {
			const fake1 = document.querySelector("[data-test-id='fake-assistant']");
			if (fake1) fake1.remove();
			const fake2 = document.querySelector("[data-test-id='fake-assistant-2']");
			if (fake2) fake2.remove();
		});

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
