"""Minimal ACP agent for real-subprocess transport tests (AS06).

Implements just enough of the Agent Protocol to exercise AcpSessionTransport:
initialize → new_session → prompt with turn-counting assistant messages.

Emits normalized intra-turn events for AS18/AS20 testing using ACP SDK types:
AgentThoughtChunk (model starting), AgentMessageChunk (response),
ToolCallProgress (tool start/complete).
"""
import asyncio
import os
import sys
from typing import Any

from acp import (
    PROTOCOL_VERSION,
    run_agent,
    update_agent_message_text,
    update_agent_thought_text,
    update_tool_call,
)
from acp.schema import (
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
    TextContentBlock,
)

_turn_counter: int = 0


class FakeAgent:
    """Stub ACP agent that echoes turn-N on each prompt.

    Emits normalized intra-turn events using ACP SDK types:
    thought (model started), assistant-message (response),
    tool-call pending (tool started), tool-call completed (tool done).
    """

    def __init__(self, client_connection: Any) -> None:
        self._conn = client_connection

    async def initialize(
        self,
        protocol_version: int,
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

        conn = self._conn
        if conn is None:
            return PromptResponse(stop_reason="end_turn")

        # AS06 completion (RV590): a "flood" prompt emits enough
        # assistant-message chunks within ONE turn to exceed the transport's
        # MAX_EVENTS count budget (the budget that actually bounds the
        # gateway's compact-mode path, since only the small `ext` header —
        # never `event.text` — counts toward the byte budget), driving the
        # real bounded-eviction path over a live subprocess rather than only
        # a mocked connection. Count is env-controlled for speed/tuning.
        prompt_text = _first_text(prompt)
        if prompt_text == "test-fs-terminal":
            # AS68 real-subprocess proof: drive the client's fs/terminal
            # methods for real over the live ACP wire, not mocked. Writes a
            # file, reads it back, runs a real command, and reports success
            # via the final assistant message so the test can assert without
            # its own client-side introspection.
            write_result = await conn.write_text_file(
                session_id=session_id, path="as68_proof.txt", content="AS68_FS_PROOF"
            )
            read_result = await conn.read_text_file(session_id=session_id, path="as68_proof.txt")
            term = await conn.create_terminal(
                session_id=session_id,
                command=sys.executable,
                args=["-c", "print('AS68_TERMINAL_PROOF')"],
            )
            await conn.wait_for_terminal_exit(session_id=session_id, terminal_id=term.terminal_id)
            output = await conn.terminal_output(session_id=session_id, terminal_id=term.terminal_id)
            await conn.release_terminal(session_id=session_id, terminal_id=term.terminal_id)
            ok = (
                read_result.content == "AS68_FS_PROOF"
                and "AS68_TERMINAL_PROOF" in output.output
            )
            await conn.session_update(
                session_id,
                update_agent_message_text("AS68_OK" if ok else "AS68_FAIL"),
            )
            return PromptResponse(stop_reason="end_turn")

        if prompt_text == "flood":
            count = int(os.environ.get("FAKE_ACP_FLOOD_EVENTS", "10200"))
            await conn.session_update(
                session_id, update_agent_thought_text("[model] flood starting")
            )
            for i in range(count):
                await conn.session_update(session_id, update_agent_message_text(f"m{i}"))
            return PromptResponse(stop_reason="end_turn")

        # Emit normalized intra-turn events for AS18/AS20 testing.
        # Sequence mirrors real ACP agent lifecycle:
        #   thought (model starting) → assistant-message (response)
        #   → tool-call pending (tool started) → tool-call completed → result

        # 1. Model started — AgentThoughtChunk (SDK type for thought events)
        await conn.session_update(
            session_id,
            update_agent_thought_text(f"[model] turn-{_turn_counter} starting"),
        )

        # 2. Assistant message chunk — AgentMessageChunk
        msg = f"turn-{_turn_counter}"
        await conn.session_update(session_id, update_agent_message_text(msg))

        # 3. Tool started — ToolCallProgress with status "pending"
        await conn.session_update(
            session_id,
            update_tool_call(f"tc-{_turn_counter}", title="echo", status="pending"),
        )

        # 4. Tool completed — ToolCallProgress with status "completed"
        await conn.session_update(
            session_id,
            update_tool_call(f"tc-{_turn_counter}", title="echo", status="completed"),
        )

        return PromptResponse(stop_reason="end_turn")


def _first_text(prompt: list[Any]) -> str | None:
    for block in prompt:
        text = getattr(block, "text", None)
        if text is not None:
            return str(text)
    return None


def main() -> None:
    """Entry point — create agent with client connection and run."""

    def factory(client_conn: Any) -> FakeAgent:
        return FakeAgent(client_conn)

    asyncio.run(run_agent(factory))  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
