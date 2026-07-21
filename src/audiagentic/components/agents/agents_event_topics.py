"""Agents-owned event topic constants.

The declarative contracts live in ``config/components/agents/events.yaml``;
this side-effect-free module is the Python import surface for publishers and
subscribers inside the owning component.
"""

GATEWAY_REQUESTED_TOPIC = "agents.llm.gateway.requested"
GATEWAY_CANCEL_REQUESTED_TOPIC = "agents.llm.gateway.cancel-requested"
GATEWAY_PROFILE_RELOADED_TOPIC = "agents.llm.gateway.profile-reloaded"

LLM_QUEUED_TOPIC = "agents.llm.queued"
LLM_STARTED_TOPIC = "agents.llm.started"
LLM_COMPLETED_TOPIC = "agents.llm.completed"
LLM_FAILED_TOPIC = "agents.llm.failed"
LLM_CANCELLED_TOPIC = "agents.llm.cancelled"
LLM_REJECTED_TOPIC = "agents.llm.rejected"
LLM_INTERRUPTED_TOPIC = "agents.llm.interrupted"

SESSION_OPENED_TOPIC = "agents.session.opened"
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
