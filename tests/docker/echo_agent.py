"""Echo agent for ACP protocol validation (Docker smoke fixture).

Minimal server that accepts one prompt, emits an assistant-message chunk
echoing the prompt text, then terminates with end_turn.

Speaks the ACP JSON-RPC protocol over stdio as expected by
agent-client-protocol's spawn_agent_process.

Usage:
    python -m tests.docker.echo_agent [--port 8080]
"""
from __future__ import annotations

import asyncio
import json
import sys


def _send(msg: dict) -> None:
    """Write a JSON-RPC message to stdout (no newline between messages)."""
    line = json.dumps(msg)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _parse_request(line: str) -> dict | None:
    try:
        msg = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(msg, dict) and "method" in msg:
        return msg
    return None


async def handle_session_update(session_id: str, params: dict) -> None:
    """Echo back the session update content as an agent_message_chunk."""
    text = params.get("text", "echo")
    _send({
        "jsonrpc": "2.0",
        "method": "session_update",
        "params": {
            "sessionId": str(session_id),
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "text": f"echo: {text}",
            },
        },
    })


async def handle_prompt(params: dict) -> None:
    """Handle a prompt request — echo the text and terminate."""
    session_id = params.get("sessionId", "test-session")
    prompt_content = params.get("prompt", [])
    text = "unknown"
    for block in prompt_content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "unknown")
            break

    # Send assistant-message chunk echoing the prompt
    await handle_session_update(session_id, {"text": text})

    # Send result with end_turn stop_reason
    _send({
        "jsonrpc": "2.0",
        "method": "prompt_result",
        "params": {
            "sessionId": str(session_id),
            "result": {
                "stopReason": "end_turn",
            },
        },
    })

    # Exit after one prompt — this is a fixture, not a long-running server
    sys.exit(0)


async def main() -> None:
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin.buffer)

    while True:
        line = await reader.readline()
        if not line:
            break
        request = _parse_request(line.decode("utf-8"))
        if request is None:
            continue

        method = request.get("method", "")
        params = request.get("params", {})
        id_val = request.get("id")

        if method == "initialize":
            _send({
                "jsonrpc": "2.0",
                "id": id_val,
                "result": {"protocolVersion": 1},
            })
        elif method == "new_session":
            session_id = params.get("sessionId", "test-session")
            _send({
                "jsonrpc": "2.0",
                "id": id_val,
                "result": {"sessionId": str(session_id)},
            })
        elif method == "prompt":
            await handle_prompt(params)
            break
        elif method == "session_update":
            session_id = params.get("sessionId", "test-session")
            update = params.get("update", {})
            kind = update.get("sessionUpdate", "unknown")
            if kind == "agent_message_chunk":
                await handle_session_update(session_id, update)
        else:
            # Unknown method — respond with empty result
            _send({
                "jsonrpc": "2.0",
                "id": id_val,
                "result": {},
            })


if __name__ == "__main__":
    asyncio.run(main())
