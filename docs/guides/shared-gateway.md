# Shared gateway stage 1 deployment

This guide describes the stage 1 configuration and intended deployment boundary.
It is not installed-service, live TLS, multi-client or recovery qualification
evidence. Check the implementation and deployment acceptance results before
exposing a service. Node transport and joined harness sessions are outside this
slice.

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
