# Agent-jobs semantic migration checklist

Temporary Slice 6 inventory. Legacy implementation remains installed until
each semantic family has a canonical Agent Context/Work replacement and its
equivalent tests pass.

| Family | Legacy callers | Canonical target | Status |
|---|---|---|---|
| Read-only status/list | `jobs_api.py`, event overview, CLI readers | GatewayClient Work/Context reads | pending |
| Submission/launch | prompt launch, packet runner, event observer | `submit_agent_work` + Gateway request | canonical packet Work submission added; legacy prompt/observer callers remain |
| Approval/input | approvals, session input store | Foundation interaction + Work input/WAITING | in progress |
| Triggers | event observer, event triggers | event/spool ingress + deterministic Work key | in progress — canonical evaluator added; observer adapter remains |
| Child/review | review launch, packet runner | child Work with `parent_work_id` | review launcher retired; canonical child Work API is active |
| Cancel/control | job control, CLI workflow | Work control + gateway request/session control | canonical `work-control` CLI; legacy job-control alias retired |
| Observers/dead-letter | event observer, dead letter | Foundation event/spool and gateway evidence | canonical redacted failure records and runtime read surface added; legacy observer remains |

Completed prerequisite: `AgentTask` and `AgentTaskFactory` have been retired;
MCP and live GPT-auto helpers use the public GatewayClient seam.
