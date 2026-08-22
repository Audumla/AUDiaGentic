"""Local OpenAI-compatible API provider adapter.

Passthrough to any OpenAI-compatible REST endpoint (Ollama, llama.cpp, vLLM,
LiteLLM, etc.). No CLI — all execution flows through the HTTP API.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from audiagentic.components.providers.adapters.base_runner import resolve_execution_model
from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)

_OPENAI_ERROR_CODES = frozenset({
    "invalid_request_error",
    "api_error",
    "rate_limit_error",
    "model_not_found",
    "auth_error",
})


@dataclass(frozen=True)
class _ApiResult:
    status_code: int
    headers: dict[str, str]
    body: str
    stream: bool


def _build_request(
    base_url: str,
    api_key: str | None,
    model: str,
    messages: list[dict[str, Any]],
    stream: bool,
    timeout: float,
    extra_params: dict[str, Any] | None = None,
) -> tuple[urllib.request.Request, dict[str, Any]]:
    """Build an OpenAI-compatible chat completion request.

    Returns (request, body_dict) tuple.
    """
    body = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }
    if extra_params:
        body.update(extra_params)

    payload = json.dumps(body).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json" if not stream else "text/event-stream",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=payload,
        headers=headers,
        method="POST",
    )
    return req, body


def _read_stream_response(
    response: Any,
) -> list[str]:
    """Read an SSE stream and extract text content from assistant messages."""
    text_parts: list[str] = []
    buffer = ""

    for line in response.read().decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue

        data = line[len("data: "):]
        if data == "[DONE]":
            break

        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue

        delta = event.get("delta", {})
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str) and content:
                text_parts.append(content)

    return text_parts


def _parse_non_stream_response(
    body: str,
) -> dict[str, Any]:
    """Parse a non-streaming OpenAI chat completion response."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {"kind": "adhoc", "raw_error": body}

    if not isinstance(data, dict):
        return {"kind": "adhoc", "raw_error": str(data)}

    error = data.get("error")
    if isinstance(error, dict):
        return {
            "kind": "error",
            "error_code": error.get("code"),
            "error_message": error.get("message"),
        }

    choices = data.get("choices", [])
    if choices:
        first = choices[0]
        if isinstance(first, dict):
            msg = first.get("message", {})
            if isinstance(msg, dict):
                content = msg.get("content", "")
                return {
                    "kind": "completion",
                    "completion_text": content,
                    "model": data.get("model"),
                    "usage": data.get("usage"),
                }

    return {"kind": "adhoc", "raw_body": body}


def _build_messages(packet_ctx: dict[str, Any], prompt_body: str | None) -> list[dict[str, Any]]:
    """Build OpenAI-compatible messages from packet context."""
    from audiagentic.components.providers.providers_api import build_admitted_agent_prompt
    admitted = build_admitted_agent_prompt(
        {**packet_ctx, "prompt-body": prompt_body},
        {"default-model": packet_ctx.get("model-id")},
        provider_id="local-openai", title="Local OpenAI",
    )
    system_prompt = (
        "AUDiaGentic execution request. "
        f"job={packet_ctx.get('job-id')} "
        f"packet={packet_ctx.get('packet-id')} "
        f"provider={packet_ctx.get('provider-id', 'local-openai')} "
        f"workflow={packet_ctx.get('workflow-profile')}. "
        "Return a concise execution summary or the blocking reason if execution is impossible."
    )

    messages = [{"role": "system", "content": system_prompt}]

    user_content = admitted

    messages.append({"role": "user", "content": user_content})
    return messages


def _fetch_api_key(provider_cfg: dict[str, Any]) -> str | None:
    """Resolve API key from provider config or environment."""
    return (
        provider_cfg.get("api-key")
        or provider_cfg.get("apiKey")
        or provider_cfg.get("api_key")
        or provider_cfg.get("OPENAI_API_KEY")
    )


def _resolve_base_url(provider_cfg: dict[str, Any]) -> str:
    """Resolve API base URL from provider config."""
    return (
        provider_cfg.get("api-base-url")
        or provider_cfg.get("apiBaseUrl")
        or provider_cfg.get("api_base_url")
        or "https://api.openai.com"
    )


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    """Execute a provider request against an OpenAI-compatible API endpoint."""
    base_url = _resolve_base_url(provider_cfg)
    api_key = _fetch_api_key(provider_cfg)
    model = resolve_execution_model(packet_ctx, provider_cfg)

    if not model:
        raise AudiaGenticError(
            code="VAL-OPENAI-001",
            kind="providers",
            message="model-id or default-model is required for OpenAI-compatible endpoint",
            details={"provider-id": "local-openai"},
        )

    prompt_body = packet_ctx.get("prompt-body")
    messages = _build_messages(packet_ctx, prompt_body)

    timeout_seconds = provider_cfg.get("timeout-seconds", 120.0)
    stream = provider_cfg.get("stream", True)

    extra_params = {}
    exec_policy = provider_cfg.get("execution-policy", {})
    if exec_policy:
        temperature = exec_policy.get("temperature")
        if temperature is not None:
            extra_params["temperature"] = float(temperature)
        max_tokens = exec_policy.get("max-tokens") or exec_policy.get("max_tokens")
        if max_tokens is not None:
            extra_params["max_tokens"] = int(max_tokens)
        top_p = exec_policy.get("top-p") or exec_policy.get("top_p")
        if top_p is not None:
            extra_params["top_p"] = float(top_p)
        presence_penalty = exec_policy.get("presence-penalty") or exec_policy.get("presence_penalty")
        if presence_penalty is not None:
            extra_params["presence_penalty"] = float(presence_penalty)
        frequency_penalty = exec_policy.get("frequency-penalty") or exec_policy.get("frequency_penalty")
        if frequency_penalty is not None:
            extra_params["frequency_penalty"] = float(frequency_penalty)

    req, _ = _build_request(
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=messages,
        stream=stream,
        timeout=timeout_seconds,
        extra_params=extra_params or None,
    )

    job_id = packet_ctx.get("job-id")
    prompt_id = packet_ctx.get("prompt-id")
    surface = packet_ctx.get("surface")
    provider_id = packet_ctx.get("provider-id", "local-openai")
    stage = packet_ctx.get("workflow-profile")
    working_root = packet_ctx.get("working-root")

    try:
        if stream:
            response = urllib.request.urlopen(req, timeout=timeout_seconds)
            text_parts = _read_stream_response(response)
            completion_text = "".join(text_parts).strip()
            return {
                "provider-id": provider_id,
                "status": "ok",
                "execution-mode": "api",
                "model": model,
                "output": completion_text,
                "stdout": completion_text,
                "stderr": "",
                "returncode": 0,
                "command": f"{base_url}/v1/chat/completions",
                "stream": True,
                "completion": {
                    "provider-id": provider_id,
                    "job-id": job_id,
                    "prompt-id": prompt_id,
                    "surface": surface,
                    "stage": stage,
                    "status": "ok",
                    "result-source": "response-body",
                    "normalization-method": "api-native-json",
                    "subject": {
                        "kind": "completion",
                        "completion_text": completion_text,
                        "model": model,
                    },
                },
            }
        else:
            response = urllib.request.urlopen(req, timeout=timeout_seconds)
            body = response.read().decode("utf-8", errors="replace")
            parsed = _parse_non_stream_response(body)

            if parsed.get("kind") == "error":
                raise AudiaGenticError(
                    code="EXT-OPENAI-001",
                    kind="providers",
                    message=f"OpenAI API error: {parsed.get('error_message', 'unknown error')}",
                    details={
                        "provider-id": provider_id,
                        "error_code": parsed.get("error_code"),
                        "model": model,
                    },
                )

            completion_text = parsed.get("completion_text", body)
            usage = parsed.get("usage")

            return {
                "provider-id": provider_id,
                "status": "ok",
                "execution-mode": "api",
                "model": model,
                "output": completion_text,
                "stdout": completion_text,
                "stderr": "",
                "returncode": 0,
                "command": f"{base_url}/v1/chat/completions",
                "stream": False,
                "usage": usage,
                "completion": {
                    "provider-id": provider_id,
                    "job-id": job_id,
                    "prompt-id": prompt_id,
                    "surface": surface,
                    "stage": stage,
                    "status": "ok",
                    "result-source": "response-body",
                    "normalization-method": "api-native-json",
                    "subject": {
                        "kind": "completion",
                        "completion_text": completion_text,
                        "model": model,
                        "usage": usage,
                    },
                },
            }

    except urllib.error.HTTPError as exc:
        error_body = ""
        try:
            error_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass

        error_detail = error_body
        try:
            err_json = json.loads(error_body)
            err_obj = err_json.get("error", {})
            if isinstance(err_obj, dict):
                error_detail = err_obj.get("message", error_body)
        except (json.JSONDecodeError, ValueError):
            pass

        raise AudiaGenticError(
            code="EXT-OPENAI-002",
            kind="providers",
            message=f"OpenAI API HTTP {exc.code}: {error_detail}",
            details={
                "provider-id": provider_id,
                "status_code": exc.code,
                "model": model,
                "error_detail": error_detail,
            },
        ) from exc

    except urllib.error.URLError as exc:
        raise AudiaGenticError(
            code="NET-OPENAI-001",
            kind="providers",
            message=f"OpenAI API connection failed: {exc.reason}",
            details={
                "provider-id": provider_id,
                "base-url": base_url,
                "model": model,
            },
        ) from exc

    except TimeoutError as exc:
        raise AudiaGenticError(
            code="TO-OPENAI-001",
            kind="providers",
            message=f"OpenAI API request timed out after {timeout_seconds}s",
            details={
                "provider-id": provider_id,
                "base-url": base_url,
                "model": model,
                "timeout": timeout_seconds,
            },
        ) from exc
