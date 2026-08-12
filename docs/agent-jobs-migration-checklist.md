# Agent-jobs semantic migration checklist

Temporary Slice 6 inventory. Legacy implementation remains installed until
each semantic family has a canonical Agent Context/Work replacement and its
equivalent tests pass.

| Family | Legacy callers | Canonical target | Status |
|---|---|---|---|
| Read-only status/list | `jobs_api.py`, event overview, CLI readers | GatewayClient Work/Context reads | pending |
| Submission/launch | prompt launch, packet runner, event observer | `submit_agent_work` + Gateway request | in progress |
| Approval/input | approvals, session input store | Foundation interaction + Work input/WAITING | in progress |
| Triggers | event observer, event triggers | event/spool ingress + deterministic Work key | in progress — canonical evaluator added; observer adapter remains |
| Child/review | review launch, packet runner | child Work with `parent_work_id` | in progress — child delegation added; review runner remains |
| Cancel/control | job control, CLI workflow | Work control + gateway request/session control | pending |
| Observers/dead-letter | event observer, dead letter | Foundation event/spool and gateway evidence | pending |

Completed prerequisite: `AgentTask` and `AgentTaskFactory` have been retired;
MCP and live GPT-auto helpers use the public GatewayClient seam.
