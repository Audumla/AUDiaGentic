import asyncio
from typing import Any, cast

from acp import (
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
    run_agent,
    text_block,
    update_agent_message,
    update_agent_thought_text,
    update_tool_call,
)
from acp.schema import ListSessionsResponse

# Per-session turn counter: session_id -> int
_sessions: dict[str, int] = {}


class FakeAcpAgent:
    """Minimal ACP agent that echoes prompts with a per-session turn counter.

    State is kept in-process across turns — turn 2's response contains the
    cumulative count from turn 1 + turn 2, proving context retention.

    Emits normalized intra-turn events for AS18/AS20 testing using ACP SDK types:
    AgentThoughtChunk (model started), AgentMessageChunk (response),
    ToolCallProgress (tool start/complete).
    """

    def __init__(self) -> None:
        self._conn: Any = None

    def on_connect(self, conn: Any) -> None:
        """Store the connection reference for session_update calls."""
        self._conn = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: Any = None,
        client_info: Any = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        return InitializeResponse(protocol_version=protocol_version)

    async def new_session(
        self,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[Any] | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        session_id = f"fake-session-{cwd.split('/')[-1] or 'root'}"
        _sessions[session_id] = 0
        return NewSessionResponse(session_id=session_id)

    async def prompt(
        self,
        session_id: str,
        prompt: list[Any],
        **kwargs: Any,
    ) -> PromptResponse:
        turn = _sessions.get(session_id, 0) + 1
        _sessions[session_id] = turn

        # Extract prompt text for echo
        prompt_text = ""
        for block in prompt:
            if isinstance(block, dict) and block.get("type") == "text":
                prompt_text = block.get("text", "")
            elif hasattr(block, "type") and getattr(block, "type", None) == "text":
                prompt_text = getattr(block, "text", "")

        # Emit normalized intra-turn events for AS18/AS20 testing.
        # Sequence: thought (model started) → agent_message_chunk (response)
        #   → tool_call pending (tool started) → tool_call completed

        # 1. Model started — AgentThoughtChunk
        await self._conn.session_update(
            session_id,
            update_agent_thought_text(f"[model] turn-{turn} starting"),
        )

        # 2. Assistant message chunk (the actual response) — AgentMessageChunk
        await self._conn.session_update(
            session_id,
            update_agent_message(
                text_block(f"[turn={turn}] echo: {prompt_text}")
            ),
        )

        # 3. Tool started — ToolCallProgress with status "pending"
        await self._conn.session_update(
            session_id,
            update_tool_call(f"tc-{turn}", title="echo", status="pending"),
        )

        # 4. Tool completed — ToolCallProgress with status "completed"
        await self._conn.session_update(
            session_id,
            update_tool_call(f"tc-{turn}", title="echo", status="completed"),
        )

        return PromptResponse(stop_reason="end_turn")

    # Minimal stubs for required Agent protocol methods that won't be called
    async def load_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[Any] | None = None,
        additional_directories: list[str] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        return []

    async def list_sessions(
        self,
        cwd: str | None = None,
        cursor: str | None = None,
        **kwargs: Any,
    ) -> ListSessionsResponse:
        return ListSessionsResponse(sessions=[])

    async def set_session_mode(
        self,
        session_id: str,
        mode_id: str,
        **kwargs: Any,
    ) -> list[str]:
        return []

    async def set_config_option(
        self,
        config_id: str,
        session_id: str,
        value: str | bool,
        **kwargs: Any,
    ) -> list[str]:
        return []

    async def authenticate(
        self,
        method_id: str,
        **kwargs: Any,
    ) -> list[str]:
        return []

    async def fork_session(
        self,
        session_id: str,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        return []

    async def resume_session(
        self,
        session_id: str,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        return []

    async def close_session(
        self,
        session_id: str,
        **kwargs: Any,
    ) -> list[str]:
        return []


async def main() -> None:
    agent = FakeAcpAgent()
    # Cast to Agent protocol type for run_agent parameter compatibility
    from acp import Agent
    await run_agent(cast("Agent", agent))


if __name__ == "__main__":
    asyncio.run(main())
