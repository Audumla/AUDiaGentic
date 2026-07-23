# Creating a Harness

How to add a new interactive coding-agent harness (pi, opencode, and their
future siblings) to the `audiagentic` launcher. Companion:
[ARCHITECTURE_STANDARDS.md](ARCHITECTURE_STANDARDS.md) (the non-negotiable
rules this guide operationalizes) and
[CREATING_A_COMPONENT.md](CREATING_A_COMPONENT.md) (the sibling guide for
product components).

## 1. Mental model

A **harness** is not a separate concept from a **provider** — it is the same
CLI (pi, opencode, claude, codex, ...), used two ways:

- **Standalone**: the user runs the CLI directly, outside AUDiaGentic. It reads
  its own native config and sees whatever it natively discovers.
- **AUDiaGentic-driven**: `audiagentic` launches the *same, system-installed*
  CLI — never an embedded/bundled copy — pointed at an AUDiaGentic-curated
  view of MCP tools, project context, and extensions.

The launcher never silently installs or embeds a harness. Explicit provider
lifecycle installation may install the same CLI into the system toolchain;
after that, `runtime.harness.resolution` treats it exactly like any other CLI
found on `PATH`. It tries the configured preference order (`harness.order` in
the `harness/ag` config namespace). Reorder or extend that list per project or
user; do not add a second private harness binary location.

## 2. Where things live

A harness spans **two** trees, split by what each owns:

```text
src/audiagentic/
  runtime/harness/<type>/            # RUNTIME ORCHESTRATION: drives a launch
    install/
      __init__.py                    # install_to, cleanup_runtime, refresh_*
      config.py                      # materialize_agent_config (rig, models, settings)
    runner/
      __init__.py                    # build_global_context, run_agent, env_flag
      command.py                     # build_agent_command, _build_run_env

  components/providers/adapters/<type>/   # PLATFORM COMPONENT: owns the provider
    adapter.py                       # one-shot `run()` entrypoint
    acp.py                           # optional: build_acp_launch (live ACP sessions)
    mcp_surface.py                   # optional: prepare_mcp_surface (launch-time MCP curation)
```

`runtime/harness/<type>/` is **data-thin, orchestration-heavy**: it decides
*when* to launch and which model/rig/process lifecycle applies. Generic
provider services collect and translate standard MCP projections; a harness
runner must not repeat that mapping. Runtime orchestration must never durably
manage a provider's own config files or reach into adapter internals directly.

`components/providers/adapters/<type>/` is **mechanism-heavy, provider-owned**:
it decides *how* a specific CLI achieves what was asked — flags, env vars,
config file quirks, third-party version drift. Nothing outside this package
should need to know these details.

### The dependency boundary this split exists to enforce

Per [ARCHITECTURE_STANDARDS.md §1](ARCHITECTURE_STANDARDS.md#1-dependency-boundaries):

| Layer | May depend on |
|---|---|
| `runtime.harness` (Runtime orchestration) | Foundation; `runtime/system`; **approved platform public APIs** (`providers_api`) |
| `components.providers` (Platform component) | Foundation; `runtime/system` — **never runtime orchestration** |

So: `runtime.harness.<type>.runner` may call `providers_api.*`. A provider
adapter under `components.providers.adapters.<type>` must **never** import
anything from `runtime.harness` — if you find yourself doing that, the
information it needs should be passed into the request, or the underlying
primitive (e.g. system-CLI resolution) belongs in `components.providers`
instead. This was a real, discovered violation fixed while writing this guide
— check `components/providers/adapters/pi/system.py` for the corrected
pattern (provider owns its own `shutil.which`-based resolution, never borrows
`runtime.harness.resolution`).

## 3. The install/runner contract

Full contract: [`runtime/harness/interface.py`](../../src/audiagentic/runtime/harness/interface.py)
(read it — this guide summarizes, that file is canonical).

Minimum to implement:

```python
# runtime/harness/<type>/install/__init__.py
def install_to(target: Path, project_root: Path | None = None) -> int: ...
def cleanup_runtime(target: Path) -> int: ...
def refresh_materialized_agent_config(target: Path, project_root: Path | None = None) -> int: ...
def refresh_harness_config_if_installed(project_root, *, reason, component_id=None) -> bool: ...
def request_runtime_reload(project_root, *, reason, component_id=None, has_mcp_servers=True) -> Path: ...
def build_runtime_sync(*, reason, component_id=None, target=..., has_mcp_servers=True) -> dict: ...

# runtime/harness/<type>/runner/__init__.py
def build_global_context(*, project_root, agent_runtime, enable_mcp) -> AgentContext: ...
def run_agent(ctx, params, *, smoke: bool) -> int: ...
def translate_agent_args(params: RunnerParams) -> list[str]: ...
def env_flag(name: str, default: bool = False) -> bool: ...
```

The facade (`runtime/harness/__init__.py`) dispatches to these via
`importlib`, resolved from `harness.type`/`harness.order` in config — it never
imports a harness package directly, and neither should any other caller.

### Smoke-mode discipline

`build_agent_command(ctx, smoke=True)` builds the fast, bounded health-check
invocation used by `audiagentic bootstrap` verification and CI. Two hard
lessons from pi's implementation, applicable to any harness:

- **Disable the CLI's own extension/plugin auto-discovery in smoke mode too**,
  not just normal-mode. Omitting this let smoke silently also load whatever
  the user has globally configured, turning a bounded health check into
  unbounded, uncontrolled work — the exact cause of a real hang once the
  curated MCP set grew past a couple of servers.
- Smoke must exit fast and deterministically. If MCP is enabled, exercise the
  same launch-surface path normal mode uses — don't special-case smoke to skip
  MCP silently, or a real integration break there won't be caught before a
  release.

## 4. MCP launch surface

This is the mechanism that makes AUDiaGentic-driven launches see *only*
AUDiaGentic-curated MCP tools (or, when supported, an explicitly configured
additive mode) — the "audiagentic-only" launch surface.

### Contract

`components/providers/contracts/mcp_launch_surface.py`:

```python
@dataclass(frozen=True)
class McpLaunchServerEntry:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()

@dataclass(frozen=True)
class McpLaunchSurfaceRequest:
    project_root: str
    runtime_root: str | None = None
    entries: tuple[McpLaunchServerEntry, ...] = ()

@dataclass(frozen=True)
class McpLaunchSurfaceResult:
    ok: bool
    supported: bool
    applied_isolation: McpLaunchIsolationTier = "unsupported"
    mechanism: str = ""           # diagnostic label, e.g. "pi-mcp-exclusive-patch"
    extra_args: tuple[str, ...] = ()
    extra_env: tuple[tuple[str, str], ...] = ()
```

Declare the provider-wide capability as
`mcp_launch_isolation_tier: exact | additive | unsupported` in the provider
descriptor. This is inherent harness capability metadata, not mutable feature
state or a per-launch setting. `applied_isolation` is the separate outcome for
one materialization attempt, so an unavailable runtime mechanism fails closed.

### Caller side (runtime.harness.\<type\>.runner)

The standard component projection and its translation into the provider
contract are shared provider-family behavior. Call the combined public API;
do not repeat collection or field mapping in each runner:

```python
def _prepare_mcp_surface(ctx: AgentContext):
    from audiagentic.components.providers import providers_api

    return providers_api.prepare_projected_provider_mcp_surface(
        ctx.project_root,
        provider_id="<your-provider-id>",
        runtime_root=ctx.launch_runtime_root,
        require_exact_isolation=True,
    )
```

Then merge the result into the built command/env:

```python
if ctx.enable_mcp:
    command.extend(_prepare_mcp_surface(ctx).extra_args)
    ...
    env.update(dict(_prepare_mcp_surface(ctx).extra_env))
```

### Provider side (components.providers.adapters.\<type\>.mcp_surface)

Implement exactly one function, discovered by convention (no registry to
edit — dropping the module *is* the registration, matching
`load_acp_launch_builder`'s pattern):

```python
# components/providers/adapters/<type>/mcp_surface.py
def prepare_mcp_surface(request: McpLaunchSurfaceRequest) -> McpLaunchSurfaceResult:
    ...
```

**Before assuming your CLI has no way to be exclusive, verify — don't guess.**
Two real, opposite outcomes from this codebase's own harnesses:

- **pi**: has a documented, upstream-confirmed 4-source MCP discovery merge
  with no native exclusivity flag (verified against installed source *and*
  upstream docs — see `pi/mcp_exclusive_patch.py`'s docstring for the full
  evidence trail). AUDiaGentic ships a small, additive, version-robust patch
  to the system-installed adapter (`pi/mcp_exclusive_patch.py`) — new flag
  (`--mcp-exclusive`), never touches existing documented behavior. If you must
  patch a third-party adapter: anchor on stable landmarks (function names, not
  exact surrounding text), fail closed (do nothing rather than half-apply if
  an anchor isn't found), and prove idempotency + syntactic validity against
  the *actually installed* file, not an assumed version.
- **opencode**: has a genuinely native mechanism —
  `OPENCODE_CONFIG_CONTENT`, a per-process env var, empirically confirmed to
  merge *after* project config and support `enabled: false` to suppress a
  specific server without touching any file. Zero patching needed. Check for
  this kind of native lever first; it's strictly better when it exists.

Either way: **empirically confirm the mechanism actually restricts
visibility** — don't trust that setting a flag/env var did anything until
you've run the harness for real and compared exclusive vs. additive output
side by side. A unit test on your own contract types proves your code is
internally consistent; it does not prove the third-party CLI honored it.

### What NOT to do

- Don't have the provider adapter call `collect_component_mcp_entries` itself, or import
  anything from `runtime.harness` — that's the boundary violation this guide
  exists to prevent. The caller computes `entries`; the adapter only knows
  mechanism.
- Don't write a durable/shared MCP config file from the launch-surface path.
  A provider may atomically materialize a request-owned ephemeral file below
  `runtime_root` when its CLI requires one. That file is immutable for the
  child lifetime and removed with the request runtime. Durable native config
  remains the separate `mcp_config`/`ManagedConfigSpec` contract.
- Don't assume a mechanism that isn't wired into every place the CLI is
  spawned. `pi-acp` (the ACP bridge used for isolated/gateway-dispatched
  agent jobs) spawns the underlying `pi` binary with a **hardcoded** arg list
  — it does not forward `--mcp-config`/`--extension`/`--mcp-exclusive` at
  all. If your harness has more than one launch path (interactive CLI vs. an
  ACP/RPC bridge), verify the surface mechanism actually reaches *each* one;
  don't assume flag-based control works everywhere env-based control might be
  needed, or vice versa.

## 5. Viability protocol for another harness

Do not declare a harness viable from configuration generation alone. Complete
these gates in order and retain the evidence anchor in its provider descriptor.

### Gate A — executable and ownership

1. Resolve exactly one system executable through the shared harness resolver.
2. If explicit lifecycle install is supported, prove install, probe, and
   uninstall in a clean container. The runtime must not create a second copy.
3. Identify every process launch path: direct CLI, one-shot provider runner,
   ACP/RPC bridge, daemon, plugin host, or wrapper. A path not inventoried is
   unsupported, not implicitly covered.

### Gate B — durable native use

1. Declare the provider's native `ManagedConfigSpec` and materialize the
   **functional** projection (`installed && enabled`).
2. Start the CLI natively from a terminal without AUDiaGentic launch wrappers.
3. Invoke a sentinel projected tool and prove user-owned/foreign native config
   survives reconciliation byte-for-byte where it is outside our ownership.

### Gate C — direct request isolation

1. Create a disposable home plus project config containing an ambient sentinel
   MCP server.
2. Launch with a curated set that excludes the sentinel, then query the
   harness's real tool inventory or invoke a selected tool.
3. Repeat with an empty set. Empty must expose zero MCP servers, never trigger
   native fallback.
4. Run two launches concurrently with disjoint sets. Assert distinct runtime
   roots/artifacts and no cross-visibility.
5. Kill one child and verify cleanup removes only its request root while the
   native config and other job remain unchanged.

Only an observed exact set permits `mcp_launch_isolation_tier: exact`.
Additive discovery is `additive`; inability to control discovery is
`unsupported`. Required internal jobs must fail before spawning for the latter
two outcomes.

### Gate D — every bridge independently

Repeat Gate C for each ACP/RPC/daemon path. Passing the direct CLI gate does not
cover a bridge that constructs its own child command. Verify what the bridge
actually forwards by source inspection plus a real visible-tool test. If the
bridge cannot forward the proven mechanism, use a provider-owned request
wrapper/env override or declare that path unsupported.

### Gate E — bounded operational behavior

- Tool listing and one harmless management call complete under explicit
  startup/call deadlines.
- Secrets in MCP entry environments never appear in logs, results, timelines,
  or generated diagnostics.
- Unsupported versions and failed patch/probe anchors fail closed with a stable
  provider error.
- Windows and Linux package-root/config precedence are proven separately when
  both are supported.

### Minimum test placement

| Proof | Test tier |
|---|---|
| Projection selection, duplicate-name rejection, contract validation | unit |
| Request artifact ownership, empty/disjoint sets, cleanup | integration |
| Real CLI visible-tool/sentinel exclusion | opt-in E2E or Docker |
| Clean install/probe/uninstall and platform package layout | isolated Docker recipe |
| Direct and every bridge launch path | separate E2E cases |

Mocks may prove our composition, but never third-party exclusivity. A capability
fact must point to an installed-artifact or execution test, including the exact
tool version and platform.

## 6. Checklist

- [ ] `runtime/harness/<type>/install/` and `runner/` implement the full
      contract in `interface.py`.
- [ ] `components/providers/adapters/<type>/adapter.py` exists (one-shot run)
      and the provider descriptor (`config/providers/<type>.yaml`) is
      registered with its own `mcp_config` (durable, standalone-usage config).
- [ ] Add `<type>` to `harness.order` in
      `config/provisioning/harness/ag.yaml` (or leave it for
      user/project-local override only, if not a default candidate).
- [ ] Smoke mode disables the CLI's own extension/plugin auto-discovery.
- [ ] If launch-time MCP curation is needed: `mcp_surface.py` implements
      `prepare_mcp_surface`, verified against the *installed* CLI (not
      assumed from docs), and the runner uses
      `providers_api.prepare_projected_provider_mcp_surface` — never a direct
      adapter import or repeated entry conversion.
- [ ] Empirically confirm exclusivity end-to-end: run the harness for real
      with entries that differ from what it would natively discover, and
      diff exclusive vs. additive output. Don't ship on a unit test alone.
- [ ] If an ACP/RPC bridge exists for this harness, verify whether the launch
      surface mechanism reaches it — it may need a different (env-based
      rather than flag-based, or vice versa) mechanism than the direct CLI
      path.
- [ ] Empty-set, concurrent-disjoint-set, ambient-sentinel, crash-cleanup, and
      native-config-unchanged proofs pass.
- [ ] Descriptor capability evidence names the tested version/platform and a
      real installed-artifact or execution test.
