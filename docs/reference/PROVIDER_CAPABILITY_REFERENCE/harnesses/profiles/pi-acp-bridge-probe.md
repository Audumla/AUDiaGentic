<!-- PROBE: AS40 validate-first — pi-acp bridge child-process spawn mechanics -->

# pi-acp Bridge Spawn Probe — AS40

**Probe date:** 2026-07-28
**Installed versions:** `pi` (`@earendil-works/pi-coding-agent`) **0.82.1**; `pi-acp` **0.0.32** (resolved via `npx --yes pi-acp`, cached under `_npx/6d9a10beb461d405/node_modules/pi-acp/dist/index.js`)
**Probe method:** Source-only inspection of the installed `pi-acp` bundle (`dist/index.js`, minified/bundled but readable). No model invocations. No code modifications.

Supersedes the "pi-acp separate package? Does not exist" finding in
[pi-status-probe.md](pi-status-probe.md) §9 (probed 2025-07-19 against pi
0.80.10) — `pi-acp` now exists as a real, independently-versioned third-party
npm package (`svkozak/pi-acp`, MIT), not part of `@earendil-works/pi-coding-agent`.
This probe is scoped to AS40's actual insertion point: how `pi-acp` spawns its
`pi --mode rpc` child, since AS40's tee shim is substituted at that exact spawn.

---

## 1. Command resolution — confirms `PI_ACP_PI_COMMAND` is the real hook

```js
// src/pi-rpc/command.ts (bundled)
function defaultPiCommand() {
  return platform() === "win32" ? "pi.cmd" : "pi";
}
function getPiCommand(override) {
  return override ?? defaultPiCommand();
}
function shouldUseShellForPiCommand(cmd) {
  if (platform() !== "win32") return false;
  const normalized = cmd.trim().toLowerCase();
  return normalized.endsWith(".cmd") || normalized.endsWith(".bat");
}
```

`override` is read from `process.env.PI_ACP_PI_COMMAND` at two call sites
(`dist/index.js` lines ~1887, ~1958). This is exactly the hook
`acp.py::_materialize_pi_command_wrapper` already installs today — confirms
AS40 does not need a new insertion point.

**Implication for the tee shim:** our existing wrapper naming
(`isolated-pi.cmd` on Windows, `isolated-pi` on POSIX, see `acp.py:30-41`) is
correctly shaped — `shouldUseShellForPiCommand` only returns `true` for
`.cmd`/`.bat` on win32, so the POSIX wrapper is exec'd directly (its shebang
must remain valid) and the Windows wrapper is shelled (`cmd.exe /c`), matching
current behavior. A future tee-shim executable must preserve this naming
convention or `pi-acp` will exec it wrong (e.g. missing shell wrapping for a
`.cmd` file, or shelling a POSIX script unnecessarily).

## 2. Spawn call — confirms hardcoded argv and full stdio piping

```js
// src/pi-rpc/process.ts, PiRpcProcess.spawn()
static async spawn(params) {
  const cmd = getPiCommand(params.piCommand);
  const args = ["--mode", "rpc", "--no-themes"];
  if (params.sessionPath) args.push("--session", params.sessionPath);
  const child = spawn(cmd, args, {
    cwd: params.cwd,
    stdio: "pipe",
    env: process.env,
    shell: shouldUseShellForPiCommand(cmd)
  });
  ...
}
```

- Argv is exactly `["--mode", "rpc", "--no-themes", ("--session", <path>)?]` —
  confirms AS40's "hardcoded arg list" claim; no MCP/extension flags are
  forwarded (matches `CREATING_A_HARNESS.md` §4's existing note that `pi-acp`
  "spawns the underlying `pi` binary with a hardcoded arg list").
- `env: process.env` — the child inherits **pi-acp's own** process
  environment, which is itself the environment AG set when it launched
  `pi-acp` (`AcpLaunch.environment`, `acp.py::_request_environment`). So a tee
  shim substituted as `cmd` sees the same per-request env AG already
  established (`PI_CODING_AGENT_DIR`, `HOME`, etc. on Windows) with **no
  additional plumbing needed** to reach it.
- `stdio: "pipe"` — all three streams (stdin/stdout/stderr) are Node pipes,
  not inherited fds. A tee shim spawned in place of `cmd` must itself expose
  the same three-pipe shape to `pi-acp`, and open its **own** separate pipes
  to the real `pi` child it spawns.

## 3. stdout consumption — confirms line-oriented parsing, ANSI/prelude tolerant

```js
const rl = readline.createInterface({ input: child.stdout });
rl.on("line", (line) => {
  if (!line.trim()) return;
  let msg;
  try { msg = JSON.parse(line); }
  catch {
    const cleaned = stripAnsi(String(line)).trimEnd();
    if (cleaned) this.preludeLines.push(cleaned);
    return;
  }
  if (msg?.type === "response") { /* correlate by id, resolve pending */ }
  for (const h of this.eventHandlers) h(msg);
});
```

- `pi-acp` reads stdout via Node's `readline` (LF-delimited, `\r` stripped by
  readline itself) — consistent with the LF-only JSONL framing documented for
  raw `pi --mode rpc` in [pi-status-probe.md](pi-status-probe.md) §2.
- Non-JSON lines are ANSI-stripped and collected as "prelude" rather than
  causing a protocol error. **This does not relax AS40's byte-transparency
  requirement** — the pi-acp-bound copy must still be untouched passthrough —
  but confirms a shim bug that emits one stray non-JSON line to the
  `pi-acp`-bound sink would not crash `pi-acp` outright (only pollute its
  prelude buffer), useful context for degraded-failure-mode testing.
- `child.stderr.on("data", () => {})` — `pi-acp` drains stderr and discards
  it. A tee shim's own stderr diagnostics are therefore invisible to
  `pi-acp`'s behavior either way; safe to use for shim-local bounded
  diagnostics per AS40's `codec_process_layer` spec.
- On `child` `"exit"`, all pending RPC promises reject — confirms AS40's
  cleanup requirement ("terminates deterministically when either the real Pi
  child exits or `pi-acp` closes its end") maps onto a real, already-handled
  `pi-acp` code path, not a hypothetical one.

## 4. Outcome for AS40 validate-first

- The insertion point, argv, env inheritance, and stdio shape are now
  confirmed against the **actually installed** `pi-acp` 0.0.32, not assumed
  from `pi`'s own RPC docs.
- Exact-version transcript fixtures (initialization, prompt, incremental
  messages, tool events, agent end/settled, abort, shutdown) as required by
  AS40's `validate_first` section are **not yet captured** by this probe —
  this probe covers the spawn/pipe mechanics the shim sits inside, not the
  RPC message stream itself (already documented at the protocol level in
  `pi-status-probe.md` §2-§8, still pending a live transcript capture at this
  exact pi-acp version).

---

*Probe completed. No code modified. No model invocations performed.*
