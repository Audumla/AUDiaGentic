"""Agents-owned event topic constants.

The declarative contracts live in ``config/components/agents/events.yaml``;
this side-effect-free module is the Python import surface for publishers and
subscribers inside the owning component.
"""

GATEWAY_REQUESTED_TOPIC = "agents.execution.gateway.requested"
GATEWAY_CANCEL_REQUESTED_TOPIC = "agents.execution.gateway.cancel-requested"
GATEWAY_PROFILE_RELOADED_TOPIC = "agents.execution.gateway.profile-reloaded"

EXECUTION_QUEUED_TOPIC = "agents.execution.queued"
EXECUTION_STARTED_TOPIC = "agents.execution.started"
EXECUTION_COMPLETED_TOPIC = "agents.execution.completed"
EXECUTION_FAILED_TOPIC = "agents.execution.failed"
EXECUTION_CANCELLED_TOPIC = "agents.execution.cancelled"
EXECUTION_REJECTED_TOPIC = "agents.execution.rejected"
EXECUTION_INTERRUPTED_TOPIC = "agents.execution.interrupted"

SESSION_OPENED_TOPIC = "agents.session.opened"
SESSION_RESUMED_TOPIC = "agents.session.resumed"  # AS49: explicit resume-after-death
SESSION_TURN_FINISHED_TOPIC = "agents.session.turn-finished"
SESSION_CLOSED_TOPIC = "agents.session.closed"
SESSION_EXPIRED_TOPIC = "agents.session.expired"
SESSION_FAILED_TOPIC = "agents.session.failed"
SESSION_ORPHANED_TOPIC = "agents.session.orphaned"

TURN_MODEL_STARTED_TOPIC = "agents.turn.model.started"
TURN_MODEL_COMPLETED_TOPIC = "agents.turn.model.completed"
TURN_TOOL_STARTED_TOPIC = "agents.turn.tool.started"
TURN_TOOL_COMPLETED_TOPIC = "agents.turn.tool.completed"

# AS19 Stage-3: status observation topic (observation-only, never transitions turn state)
TURN_STATUS_OBSERVED_TOPIC = "agents.turn.status.observed"
