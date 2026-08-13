# Agent-jobs semantic migration checklist

Slice 6 status audit. Canonical Agents Work paths own execution lifecycle.
Only ingress adapters and redacted failure evidence remain in `agent_jobs`.

| Family | Current implementation | Status |
|---|---|---|
| Read-only status/list | `components.agents.work.work_api` provides canonical Work status/list reads. The obsolete `jobs_api.py` and `event_overview.py` surfaces are deleted. | complete |
| Submission/launch | Prompt launch and packet submission require Context-backed canonical Work and deterministic Work IDs; no legacy lifecycle fallback remains. | complete |
| Approval/input | Approval and session input require explicit Work identity and use Foundation interactions/Work messages; no legacy job state/store path remains. | complete |
| Triggers | Canonical `agents.work.event_ingress.WorkEventIngress` owns configured trigger delivery and deterministic Work submission. The old observer remains only as an explicit, non-installed compatibility adapter for the historical trigger file. | complete — bounded compatibility adapter |
| Child/review | Review launch was replaced by the public child-Work API with deterministic child IDs and `parent_work_id`; the obsolete `review_launch.py` and review-launch tests are deleted. Review-specific validation/aggregation helpers remain only where still used by compatibility/reporting code. | complete |
| Cancel/control | Legacy job control API, persistence, and state-machine fallback have been removed; canonical Work/Gateway control is the only lifecycle path. | complete |
| Observers/dead-letter | Canonical event ingress and redacted failure records/read surface are implemented. The historical observer is not installed by component lifecycle. | complete — bounded compatibility adapter |

## Remaining validation

The lifecycle migration is complete. Re-run architecture/boundary tests,
targeted migration tests, the host suite, and Docker validation.

## Completed adjacent migration work

- The obsolete agent-jobs MCP/API/overview shims and duplicate Agents MCP
  shims have been removed; Agents MCP surfaces are separated by config,
  runtime, delegation, and admin responsibility.
- Protocol/export work for AS88/AS89, AS99, AS100, and ASA/Standard Agents has
  canonical Work/API coverage and architecture guards.
- Production code outside `components/agent_jobs` has no remaining imports of
  the legacy component, and the lifecycle modules have now been removed.

## Validation status

- Host unit suite: passing; only expected Windows-environment skips remain.
- Clean Docker suite and dedicated Pi RPC Docker validation: passing.
- Full provider-install Docker matrix: still requires a final complete run;
  its long-running provider setup is not evidence that the migration is done.
