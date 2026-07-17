"""Minimal ACP agent for real-subprocess transport tests (AS06).

Implements just enough of the Agent Protocol to exercise AcpSessionTransport:
initialize → new_session → prompt with turn-counting assistant messages.
"""
import asyncio
import os
from typing import Any

from acp import (
    PROTOCOL_VERSION,
    run_agent,
    update_agent_message_text,
)
from acp.schema import (
    ClientCapabilities,
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
    TextContentBlock,
)

_turn_counter: int = 0


class FakeAgent:
    """Stub ACP agent that echoes turn-N on each prompt."""

    def __init__(self, client_connection: Any) -> None:
        self._conn = client_connection

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        return InitializeResponse(protocol_version=PROTOCOL_VERSION)

    async def new_session(self, cwd: str, **kwargs: Any) -> NewSessionResponse:
        return NewSessionResponse(
            session_id=f"fake-{os.getpid()}",
        )

    async def prompt(
        self,
        session_id: str,
        prompt: list[
            TextContentBlock | Any  # other content block types
        ],
        **kwargs: Any,
    ) -> PromptResponse:
        global _turn_counter
        _turn_counter += 1

        msg = f"turn-{_turn_counter}"
        chunk = update_agent_message_text(msg)

        if self._conn is not None:
            await self._conn.session_update(session_id, chunk)

        return PromptResponse(stop_reason="end_turn")


def main() -> None:
    """Entry point — create agent with client connection and run."""

    def factory(client_conn: Any) -> FakeAgent:
        return FakeAgent(client_conn)

    asyncio.run(run_agent(factory))  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
