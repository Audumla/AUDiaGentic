# Gateway observability retention

OB02 bounds durable gateway evidence without recursively deleting request
directories.

The machine-owned policy file is selected by
\`AUDIAGENTIC_GATEWAY_RETENTION_POLICY\`, or defaults to
\`~/.audiagentic/gateway-retention.json\`. The policy may contain:

\`\`\`json
{
  "policy-id": "ops",
  "purge-enabled": false,
  "request-history-limit": 100,
  "timeline-max-bytes": 1048576,
  "observation-max-bytes": 2097152,
  "recovery-max-bytes": 1048576,
  "console-trace-max-bytes": 4194304
}
\`\`\`

The request-history limit is the number of resolved, unpinned histories kept
at full journal resolution. Older resolved histories are compacted in place;
their request directory and terminal record remain. Active, unresolved,
recovery-required, and retention-pinned records are never selected for this
rolling pass. The existing explicit archive and purge operations remain
separate and still require their existing policy and operator safeguards.

The timeline, observation, and recovery journals rebuild their byte indexes
atomically when they exceed their configured caps. The compactor keeps the
newest rows and terminal evidence. The global operator trace rotates
\`console-trace.log\` to one bounded \`.1\` backup. Environment overrides are
available for emergency tuning:

- \`AUDIAGENTIC_GATEWAY_REQUEST_RETENTION_COUNT\`
- \`AUDIAGENTIC_GATEWAY_TIMELINE_MAX_BYTES\`
- \`AUDIAGENTIC_GATEWAY_OBSERVATION_MAX_BYTES\`
- \`AUDIAGENTIC_GATEWAY_RECOVERY_MAX_BYTES\`
- \`AUDIAGENTIC_GATEWAY_CONSOLE_TRACE_MAX_BYTES\`

Operators can inspect the effective, redacted values with the privileged
\`agent_gateway_get_retention_policy\` management tool. It reports policy
identity, rolling history count, and byte caps; it never returns policy paths,
request contents, or provider data.
