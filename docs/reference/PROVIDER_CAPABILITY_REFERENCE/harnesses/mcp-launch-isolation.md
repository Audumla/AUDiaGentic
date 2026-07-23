# MCP launch isolation

AUDiaGentic separates durable native harness configuration from ephemeral
AUDiaGentic-owned launch surfaces.

Provider descriptors declare the provider-wide `mcp_launch_isolation_tier`.
Pi and OpenCode currently declare `exact`; launch builders report the concrete
`applied_isolation` outcome (`exact`, `additive`, or `unsupported`) for each
request. Internal agent jobs require `exact` and fail before dispatch otherwise.

| Launch | Selection | Materialization | Shared config mutation |
|---|---|---|---|
| Native Pi terminal | Installed and enabled functional tools | Pi/provider durable config | Managed owner only |
| `audiagentic launch` with Pi | Installed management tools | Request-owned Pi MCP JSON plus exclusive adapter flags | None |
| Pi ACP gateway session | Explicit job snapshot | Request-owned JSON and `PI_ACP_PI_COMMAND` wrapper | None |
| Native OpenCode terminal | Installed and enabled functional tools | `.opencode/opencode.json` | Managed owner only |
| `audiagentic launch` with OpenCode | Installed management tools | Inline config and isolated `XDG_CONFIG_HOME` | None |
| OpenCode ACP gateway session | Explicit job snapshot | One provider-composed inline document | None |

## Projection rules

- Management uses `propagate: audiagentic` and includes core or installed
  components even while disabled. A disabled component must retain the tool
  that can enable it.
- Functional uses `propagate: providers` and requires the component to be
  installed and enabled.
- A job surface is a concrete immutable subset selected before the provider
  boundary. Provider adapters receive entries, never component or role policy.

## Isolation rules

- Every internal job has a unique request-runtime root.
- Empty selection means no MCP servers; it never means ambient fallback.
- Provider adapters report whether the actual mechanism is exclusive.
- Internal dispatch requires exclusivity and fails before child launch when it
  is unavailable.
- Native/global/project configuration is never rewritten by job preparation.
- Generated files and wrappers are removed with the session/request runtime.

## Provider evidence

Pi's direct CLI requires the `pi-mcp-adapter` exclusivity patch because the
upstream adapter otherwise merges global, project, and override sources.
Published `pi-acp@0.0.31` accepts an ACP `mcpServers` field but does not apply it
to its Pi RPC child. AUDiaGentic uses the bridge's `PI_ACP_PI_COMMAND` override
to point at a request-owned wrapper supplying the proven direct isolation
flags.

OpenCode uses a per-process inline configuration. A request-local
`XDG_CONFIG_HOME` removes user-global config/plugins, the inline document
disables project-config MCP names not selected, and `plugin: []` prevents
configured plugins from adding an alternate tool surface.

## Reproducing the evidence

For a new harness, use the ordered viability protocol in
`docs/standards/CREATING_A_HARNESS.md`. The decisive experiment is a real
visible-tool comparison with three sets:

1. native config containing ambient sentinel `ambient-only`;
2. curated launch containing only `selected-only`;
3. curated empty launch.

An exact implementation must show `{selected-only}` and `{}` respectively,
never `ambient-only`. Repeat with two concurrent disjoint launches and for
every ACP/RPC bridge. Preserve hashes of native configuration before and after,
and record tool version, platform, launch mechanism, runtime artifact path,
and bounded startup/call timings. Generated arguments or JSON alone are not
viability evidence.
