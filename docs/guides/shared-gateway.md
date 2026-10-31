# Shared gateway stage 1 deployment

This guide describes the stage 1 configuration and intended deployment boundary.
It is not installed-service, live TLS, multi-client or recovery qualification
evidence. Check the implementation and deployment acceptance results before
exposing a service. Execution nodes (`gateway node serve`) are experimental and
not qualified; joined harness sessions are outside this slice.
The opt-in installed-package native qualification harness (server-hosted
execution only) is described in `tests/e2e/shared_gateway/README.md`.

## Server configuration

Save the following as `server.yaml`. Create the referenced directories and
provision credential files separately before loading it. Paths are resolved
relative to this YAML file, not the shell working directory. Absolute paths are
also accepted; paths are not environment-variable or home-directory templates.

```yaml
schema-version: 1
server-id: team-gateway
listen:
  host: 127.0.0.1
  port: 8765
service-root: ./state
projects:
  sample: ./projects/sample
principals:
  developer-a:
    token-file: ./secrets/developer-a.token
    projects: [sample]
    actions: [read, submit, cancel, session]
  observer:
    token-file: ./secrets/observer.token
    projects: [sample]
    actions: [read]
```

The mapping keys and fields above are the actual server parser contract:

| Field | Constraint |
| --- | --- |
| `schema-version` | Required integer `1`; booleans are rejected. |
| `server-id` | Required safe ID. |
| `listen` | Required mapping; `port` is required, `host` defaults to and must equal `127.0.0.1`. Public bind addresses are rejected. |
| `listen.port` | Integer 0–65535, excluding booleans; use a fixed nonzero port behind a proxy. Port 0 requests an ephemeral port. |
| `service-root` | Optional existing directory; omission returns `None` to use the existing owning service default. |
| `projects` | Nonempty map from public project IDs to existing server-local directories; resolved roots must be distinct. |
| `principals` | Nonempty map from principal IDs to token-file, project grants and action grants. |

IDs contain 1–64 lowercase ASCII letters, digits, underscores or hyphens, start
with a letter or digit, and contain no slash. Unknown fields, duplicate YAML
keys, unsafe YAML tags, missing required fields and wrong scalar types fail
closed. Project and action lists must be nonempty and contain no duplicates;
project grants must name configured projects. The action vocabulary is exactly
`read`, `submit`, `cancel`, `session`. Grants authorize operations on those
server project IDs; a client filesystem path cannot select a server root.

Project grants are collaborative: `read` grants access to requests and sessions
in that project, including work submitted by other principals. `cancel` and
`session` similarly authorize their operations throughout the granted project.
These grants are not per-request tenant isolation. Use separate configured
project roots for mutually untrusted tenants. Operator lifecycle, focus and purge
routes are unavailable through shared ingress regardless of grants. Default
conversation identities and explicit idempotency keys are principal-namespaced;
an observer's lease never authorizes another principal to use that lease.
An authorized `submit` caller may explicitly continue a known same-project
session. Logical client identity chooses an automatic default conversation; it
does not impose creator-only access to an explicitly selected shared session.

Omitting `service-root` is supported intentionally. The default may already be
owned by a locally running gateway; existing exclusive-owner checks still apply.
Do not bypass them or share live state between independent service owners.
Choose an explicit separate existing state directory when deploying an
independent instance alongside a local gateway.

Each principal must reference a distinct regular credential file. Resolved
aliases and hard links to the same credential file are rejected. The parser
checks file existence and permissions but does not read credentials. The ingress
startup owner must use the existing `load_auth_token` validator and reject
duplicate token values across distinct files before serving requests; config
acceptance alone does not establish that credentials are valid or unique.

Provision separate high-entropy bearer credentials for principals. On POSIX,
token files must have no group/other permission bits (for example mode `0600`);
protect containing directories and service state as well. Windows ACL control
is an external deployment responsibility: restrict secrets to the service or
client identity and designated administrators. Never place token values in
YAML, command arguments, logs or examples. Rotation requires coordinated owner
restart/reload according to the service's implemented lifecycle; this parser
does not watch files.

## Execution-node grant administration (SH38 foundation)

Node execution is not enabled by these administrative primitives. The server
parser accepts optional `node-listen` and `nodes` entries for the later transport:

```yaml
node-listen:
  host: 127.0.0.1
  port: 8766
nodes:
  build-node:
    token-file: ./secrets/build-node.token
    workspaces: {checkout: sample}
    principals: [developer-a]
    revision: 1
    enabled: true
```

Workspace IDs map to existing server project IDs; node-local paths belong only
in the node configuration. Node and user credentials must have distinct values
and files. Protect the server config and management state with local operator
filesystem permissions. Write access to the operation store grants local
operator authority; shared HTTP and MCP cannot enqueue node revocations.

Queue a revision-fenced revoke and inspect its returned operation ID:

```text
audiagentic gateway node revoke config server.yaml node build-node revision 1
audiagentic gateway node revoke status config server.yaml operation OPERATION_ID output json
audiagentic gateway node revoke help
```

An accepted operation is queued, not completed. The existing gateway operation
pump persists `enabled: false` and increments the revision before completing its
receipt. The same authority lock orders effect authorization and revocation;
network and provider calls happen outside it. An already authorized attempt may
proceed, but revocation prevents later authorization. Recovery of an interrupted
revoke recognizes the exact disabled successor revision without another write.
The CLI never starts the service or executes the revoke itself.

Use the supported writer while the service runs. Other config changes require
an owner restart; unexpected edits fail closed. An uncertain write retains
denial until durable config is reconciled. Atomic replacement inherits the
underlying filesystem durability limits; these tests do not prove hardware
power-loss persistence. Transport, node-local materialization and two-machine
qualification remain separate gates.

### Request diagnostics and node stage evidence

Use the request's authorized project context. These operator tools are on the
separate `ag-agents-gateway-ops` server (not registered by `audiagentic setup`;
install it with `audiagentic mcp install ag-agents-gateway-ops harness ID`).
`agent_task_status` stays compact;
it does not return diagnostic history or response text. For an investigation,
request `agent_task_diagnostics(request_id=...)`, then a bounded page with
`agent_task_observations(request_id=..., limit=25, tail=25)` or
`agent_task_evidence(request_id=..., include_observations=True,
include_recovery=True, limit=25)`. Follow the returned opaque cursor rather than
loading all history. A request missing from another project is inconclusive.

The server project owns
`.audiagentic/runtime/agent-execution-gateway/<request-id>/timeline.ndjson` and
`observations.ndjson`, with their indexes and retained segments. Use the existing
readers/tools across plain or compressed segments; these files belong to the
server project, not an arbitrary caller or recipient workspace.

Node instrumentation uses `node-stage-observed` alongside existing DOM events.
It records validated control milestones, original/current ownership epochs,
command hashes, bounded failure reasons and operation-local timings. A prepared
command or a completed local socket send does not prove native acceptance or a
completed response. A receipt ACK proves custody, not publication or permission
to delete evidence. Canonical request/receipt state remains authoritative;
observation history is evidence for diagnosis, never permission to replay work.
Node service composition and native end-to-end qualification remain separate
from these instrumentation primitives.

For instrumentation faults, `timeline_failure_count()` in Foundation reports
failed timeline operations, while `node_observation_failure_count()` reports
exceptions observed by the node emitter. Lower layers may isolate their own
faults, so neither is a combined count or proof of lost rows. Both are
process-local. Diagnostic failures cannot reverse committed work; authoritative
custody failures must still stop ACK/effect progression. Never retry a mutation
or blindly append again because a diagnostic counter increased.

### Recovery boundaries under node qualification

These are recovery contracts for the node implementation, not a claim that
the standalone node runtime is enabled or qualified. Connection readiness is
a reusable scheduling hint, consumed at fresh preparation; it never replaces
current grant, ownership, canonical occupancy or effect authorization checks.

| Boundary | Required disposition |
| --- | --- |
| Offline or not ready | Leave fresh work queued; historical observation may continue on an authorized channel. |
| RPC timeout or cancellation | Retire that exact channel before discarding reply correlation; reconnect to observe the original command. |
| Receipt/cursor write uncertainty | Withhold ACK and preserve custody evidence; never reset a cursor to make progress. |
| Corrupt or incomplete artifact | Keep terminal receipt evidence, defer publication and fetch immutable output within configured bounds. |
| Terminal CAS followed by cleanup interruption | Repair through the existing idempotent session finalizer without fetching or rewriting the response. |
| Diagnostic sink failure | Preserve committed work and its primary outcome; expose bounded sanitized diagnostics where the remaining sink permits. |

Readiness must renew after receipt drainage and recipient quiescence for each
command cycle. A terminal receipt can release canonical occupancy before the
producer finishes cleanup. Host qualification therefore includes this race,
lost recovery wakeups, failed callback retriggering and producer-safe shutdown.

## Connector configuration

Save this as `connector.yaml` on the client. Provision its token file with the
credential assigned to `developer-a`, using the same private-file rules.

```yaml
schema-version: 1
endpoint: https://gateway.example.com
server-id: team-gateway
project-id: sample
token-file: ./secrets/developer-a.token
ca-file: ./trust/team-ca.pem
```

The endpoint is an HTTPS origin only: no userinfo, path (including `/`), query
or fragment. An explicit port such as `:443` is allowed. Do not append
`/shared/v1`; the client owns protocol routes. `server-id` and `project-id` are
required safe IDs; the latter selects the server's configured project.
`token-file` must exist as a regular file. Optional `ca-file` must exist as a
regular file and resolves relative to the connector YAML; omit it to use the
client's default system CA trust. The config parser does not parse certificates
or prove TLS reachability. The client builds the TLS context and validates trust
during connection startup; do not disable certificate verification.

Optional `source-node-config` (experimental) names this machine's NODE
configuration and makes the connector a node-enrolled caller: **every**
submission through it becomes a node submission to the caller's own enrolled
node and workspace, derived from that file, never from tool parameters. The
binding is rechecked on each submit, and the node credential is sent only with
`submit_execution_request`. Omit it for ordinary submissions, which are
unchanged.

## Updating the runtime under a running gateway

The gateway service imports its code once, when it starts. If the installation it runs from is
then moved to other commits (an editable install pointing at a worktree, a new wheel), the
service keeps running the old code while new processes run the new code, and requests fail in
confusing ways (for example journal lock timeouts on every request). Moving the runtime and
restarting the service are one operation:

1. Move the runtime install (check out the new commit, or reinstall).
2. Restart the shared gateway service, as the operator: `audiagentic gateway restart` (it asks
   first; `non-interactive` skips the question), or the `agent_gateway_restart` admin tool
   (`ag-agents-admin`). Both call `management_api.gateway_restart`. The running service drains,
   closes its port, and starts its own replacement on the installed code; nothing signals a
   process by pid. Work in flight is drained or recovered by the normal restart recovery.
3. Restart harness sessions' MCP servers that were started before the move; they fail lazily
   with an import error until they are.

The replacement waits (up to 30 s) for the retiring service to release the port rather than
failing to bind, so a restart no longer reports "did not become ready" when it in fact worked.
`audiagentic doctor` reports the mixed state: the check `agents.gateway-code` warns when the
running service started on an older commit (or older files) than the installation it runs
from, and `agents.gateway-port` explains a port held by another home's service. Agent sessions
do not restart a shared service on their own: it needs an explicit operator request.

## Keyword CLI

```text
audiagentic gateway help
audiagentic gateway serve help
audiagentic gateway serve config server.yaml
audiagentic gateway status config connector.yaml
audiagentic gateway status config connector.yaml output json
audiagentic gateway connect config connector.yaml project ./local-project dry-run
audiagentic gateway connect config connector.yaml project ./local-project non-interactive
```

Use keywords, not `--config` or other option aliases. `serve` takes the server
configuration and is the foreground service route; supervise it with the
deployment OS. `status` takes connector configuration and requests authenticated
remote health; it does not start a local service. `connect` requires an existing
local project directory. That directory is the local binding destination and is
never sent as the remote execution root.

`dry-run` performs connector/credential/trust setup and the remote health
handshake without writing a binding. `non-interactive` expresses an explicit
request to persist the binding through the Agents configuration owner after a
successful TLS/server identity handshake. It selects the standalone
implementation and stores an absolute connector-config reference in one existing
component-state shard replacement, preserving unrelated configuration. It never
copies token contents into project configuration. The bare connect form asks for
confirmation; refusal writes nothing. Neither form installs a server locally or
falls back to embedded execution. A complete explicit local endpoint/token-file
environment override remains supported; partial overrides are rejected.

## HTTPS front door and loopback boundary

Terminate HTTPS at a reverse proxy on the same host as the shared ingress and
forward only the exclusive `/shared/v1/` protocol namespace to
`http://127.0.0.1:8765`, preserving its path. Configure the public virtual host to
deny every other path by default. Do not rewrite a public root or arbitrary
prefix into legacy gateway routes. Preserve the authentication header for the
shared ingress, overwrite trusted proxy headers, and keep credentials out of
proxy access/error logs.

The loopback listener is an internal HTTP hop, not the connector endpoint. Bind
it to loopback and block direct remote access at the OS/network boundary. Do not
forward or expose legacy control, dashboard, image, diagnostic or other local
gateway routes, even if another local service provides them. Keep any legacy
backend separate and loopback-only. A catch-all proxy to the gateway defeats
this isolation. Each shared operation, including reads and health, must enforce
principal, project and action authorization in the ingress; TLS alone supplies
no grants.

Before deployment acceptance, verify the installed foreground service, trusted
HTTPS handshake, unauthorized and cross-project denial, exclusion of legacy
routes, two independent clients, correlated terminal output, and
restart/disconnect recovery. Those checks remain deployment qualification work;
the config unit tests do not establish them.

## Operator lifecycle commands

One place manages the running service: `audiagentic gateway` with `restart`, `drain`, `resume`,
`stop [force]` and `recover reason TEXT`. Each is a thin adapter over `management_api`
(`gateway_restart`, `gateway_drain`, `gateway_resume`, `gateway_stop`, `gateway_recover`), asks
first unless `non-interactive` (`resume` never asks), and takes `output json`. `drain`, `resume`
and `stop` attach to the running service and never start one. A graceful `stop` is refused while
work is in flight; `force` stops anyway and reports the affected work. `recover` only records a
failed owner under a new epoch and never signals a pid; it is refused while the owner is
provable. Agent sessions run these only on an explicit operator request.
