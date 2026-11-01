"""A2A 1.0 JSON-RPC request handler on the pinned ``a2a-sdk`` (SH65).

A thin conversion layer: SDK protobuf requests become the dict shape ``A2aServerAdapter`` already takes, and its
task dicts become SDK ``Task`` messages. It owns no task store, queue or lifecycle (the SDK's own
``DefaultRequestHandler``/``TaskStore`` are deliberately NOT used, because Work is the single authority); the
canonical Work ports behind the adapter decide every state. Import requires the optional ``a2a`` extra
(``a2a-sdk[http-server]``); the rest of the package does not.

Not supported, and answered with the SDK's own error: streaming, resubscription, task listing, push
notification config and the authenticated extended card.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import RequestHandler
from a2a.types import a2a_pb2 as pb
from a2a.utils.errors import (
    ContentTypeNotSupportedError,
    ExtendedAgentCardNotConfiguredError,
    InternalError,
    InvalidParamsError,
    PushNotificationNotSupportedError,
    TaskNotCancelableError,
    TaskNotFoundError,
    UnsupportedOperationError,
)

from audiagentic.foundation.contracts.errors import AudiaGenticError

from .server import A2aServerAdapter

_STATE = {
    "submitted": pb.TASK_STATE_SUBMITTED, "working": pb.TASK_STATE_WORKING, "completed": pb.TASK_STATE_COMPLETED,
    "failed": pb.TASK_STATE_FAILED, "canceled": pb.TASK_STATE_CANCELED, "input-required": pb.TASK_STATE_INPUT_REQUIRED,
    "rejected": pb.TASK_STATE_REJECTED, "auth-required": pb.TASK_STATE_AUTH_REQUIRED,
}


def _request(params: pb.SendMessageRequest) -> dict[str, Any]:
    """The adapter's request dict for an SDK ``SendMessageRequest``; anything richer than text is refused."""
    message = params.message
    parts: list[dict[str, Any]] = []
    for part in message.parts:
        kind = part.WhichOneof("content")
        if kind != "text":
            raise ContentTypeNotSupportedError(f"unsupported A2A part: {kind or 'empty'}")
        parts.append({"text": part.text})
    wire: dict[str, Any] = {"messageId": message.message_id, "role": pb.Role.Name(message.role), "parts": parts}
    if message.context_id:
        wire["contextId"] = message.context_id
    if message.task_id:
        wire["taskId"] = message.task_id
    request: dict[str, Any] = {"message": wire}
    if params.configuration.return_immediately:
        request["configuration"] = {"returnImmediately": True}
    return request


def _task(view: dict[str, Any]) -> pb.Task:
    task = pb.Task(id=view["id"], context_id=view["contextId"])
    task.status.state = _STATE[view["status"]["state"]]
    for artifact in view.get("artifacts") or []:
        task.artifacts.append(pb.Artifact(
            artifact_id=artifact["artifactId"],
            parts=[pb.Part(text=part["text"]) for part in artifact["parts"]]))
    return task


def _translate(error: Exception) -> Exception:
    """Map a Work/adapter failure to the SDK error a client can act on; never leak internals."""
    if isinstance(error, AudiaGenticError):
        if error.code == "RES-AGW-153":  # no such Work: the task does not exist
            return TaskNotFoundError()
        # Conflicts, terminal Work, closed Context and the like: the request is wrong, the server is not.
        if error.code.startswith("CON-AGW-"):
            return InvalidParamsError(error.message, data={"code": error.code})
        return InternalError()
    if isinstance(error, ValueError):
        return InvalidParamsError(str(error))
    return InternalError()


class A2aSdkRequestHandler(RequestHandler):
    """``adapter`` is one fixed adapter, or a callable choosing the adapter for each call context (the facade
    builds a per-caller adapter from the caller's own credential)."""

    def __init__(self, adapter: A2aServerAdapter | Callable[[ServerCallContext], A2aServerAdapter]) -> None:
        self._adapter_for = adapter if callable(adapter) and not isinstance(adapter, A2aServerAdapter) else (lambda _context: adapter)

    def _adapter(self, context: ServerCallContext) -> A2aServerAdapter:
        return self._adapter_for(context)

    async def on_message_send(self, params: pb.SendMessageRequest, context: ServerCallContext) -> pb.Task | pb.Message:
        try:
            request = _request(params)
        except ValueError as error:  # ContentTypeNotSupportedError is an A2AError and passes through as is
            raise _translate(error) from error
        try:
            return _task(await asyncio.to_thread(self._adapter(context).send_message, request))
        except Exception as error:  # noqa: BLE001 - translated, never leaked
            raise _translate(error) from error

    async def on_get_task(self, params: pb.GetTaskRequest, context: ServerCallContext) -> pb.Task | None:
        try:
            return _task(await asyncio.to_thread(self._adapter(context).get_task, params.id))
        except Exception as error:  # noqa: BLE001
            raise _translate(error) from error

    async def on_cancel_task(self, params: pb.CancelTaskRequest, context: ServerCallContext) -> pb.Task | None:
        try:
            return _task(await asyncio.to_thread(self._adapter(context).cancel, params.id))
        except ValueError as error:
            if "cannot be canceled" in str(error):
                raise TaskNotCancelableError(str(error)) from error
            raise _translate(error) from error
        except Exception as error:  # noqa: BLE001
            raise _translate(error) from error

    async def on_list_tasks(self, params, context):
        raise UnsupportedOperationError("listing tasks is not supported")

    async def on_message_send_stream(self, params, context):
        raise UnsupportedOperationError("streaming is not supported")
        yield  # pragma: no cover - makes this an async generator for the type checker

    async def on_subscribe_to_task(self, params, context):
        raise UnsupportedOperationError("resubscription is not supported")
        yield  # pragma: no cover

    async def on_create_task_push_notification_config(self, params, context):
        raise PushNotificationNotSupportedError()

    async def on_get_task_push_notification_config(self, params, context):
        raise PushNotificationNotSupportedError()

    async def on_list_task_push_notification_configs(self, params, context):
        raise PushNotificationNotSupportedError()

    async def on_delete_task_push_notification_config(self, params, context):
        raise PushNotificationNotSupportedError()

    async def on_get_extended_agent_card(self, params, context):
        raise ExtendedAgentCardNotConfiguredError()
