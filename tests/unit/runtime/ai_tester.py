"""Local AI tester — launches embedded llama-server rig and exposes chat API.

Provides a context manager that starts the embedded llama-server (or reuses
an existing one), then exposes a simple ``chat()`` method that calls the
OpenAI-compatible /v1/chat/completions endpoint.

Designed for use in tests:

    with local_ai_tester(model_profile="qwen3.5-2b") as tester:
        result = tester.chat("What is 2+2?")
        assert result.status == "ok"

Can also be used as a pytest fixture:

    @pytest.fixture
    def ai_tester():
        with local_ai_tester() as t:
            yield t
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)


@dataclass
class ChatResult:
    """A chat completion result."""
    status: str = "ok"
    model: str | None = None
    content: str = ""
    usage: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    raw_response: dict[str, Any] | None = None


@dataclass
class LocalAITester:
    """Context-managed local AI tester backed by embedded llama-server.

    Attributes:
        base_url: The OpenAI-compatible API endpoint URL.
        model: The model currently loaded.
        port: The port the server is listening on.
        pid: The llama-server process PID (0 if not running).
    """
    base_url: str = ""
    model: str | None = None
    port: int = 0
    pid: int = 0
    endpoint: str = ""
    api_key: str | None = None
    timeout: float = 120.0

    def chat(self, prompt: str, **kwargs: Any) -> ChatResult:
        """Send a chat completion request and return the result."""
        messages = [{"role": "user", "content": prompt}]
        return self.chat_messages(messages, **kwargs)

    def chat_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Send a chat completion request with pre-built messages."""
        if not self.endpoint:
            raise AudiaGenticError(
                code="CFG-TESTER-001",
                kind="local-ai-tester",
                message="LocalAITester is not running. Use as a context manager: `with local_ai_tester() as tester:`",
            )

        model_id = model or self.model
        if not model_id:
            raise AudiaGenticError(
                code="CFG-TESTER-002",
                kind="local-ai-tester",
                message="No model available. Start the tester with a model_profile.",
            )

        body = {
            "model": model_id,
            "messages": messages,
            "stream": False,
        }
        for key in ("temperature", "max_tokens", "top_p", "presence_penalty", "frequency_penalty"):
            if kwargs.get(key) is not None:
                body[key] = kwargs[key]

        payload = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        url = f"{self.endpoint}/chat/completions"
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    error_body = resp.read().decode("utf-8", errors="replace")
                    return ChatResult(
                        status="error",
                        error_code=f"http-{resp.status}",
                        error_message=error_body,
                    )
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            err_detail = error_body
            try:
                err_json = json.loads(error_body)
                err_obj = err_json.get("error", {})
                if isinstance(err_obj, dict):
                    err_detail = err_obj.get("message", error_body)
            except (json.JSONDecodeError, ValueError):
                pass
            return ChatResult(
                status="error",
                error_code=f"http-{exc.code}",
                error_message=err_detail,
            )
        except urllib.error.URLError as exc:
            return ChatResult(
                status="error",
                error_code="connection",
                error_message=str(exc.reason),
            )
        except TimeoutError:
            return ChatResult(
                status="error",
                error_code="timeout",
                error_message=f"Request timed out after {self.timeout}s",
            )

        error = data.get("error")
        if isinstance(error, dict):
            return ChatResult(
                status="error",
                error_code=error.get("code"),
                error_message=error.get("message"),
                raw_response=data,
            )

        choices = data.get("choices", [])
        if choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message", {})
                if isinstance(msg, dict):
                    content = msg.get("content", "")
                    return ChatResult(
                        status="ok",
                        model=data.get("model"),
                        content=content,
                        usage=data.get("usage"),
                        raw_response=data,
                    )

        return ChatResult(
            status="error",
            error_message="Unexpected response format",
            raw_response=data,
        )

    def health(self) -> dict[str, Any]:
        """Check the rig health and return model info."""
        if not self.endpoint:
            return {"status": "uninitialized"}
        from audiagentic.runtime.rig.http import probe_models_endpoint
        probe = probe_models_endpoint(self.endpoint, timeout=5.0)
        if probe is None:
            return {"status": "unhealthy"}
        return {
            "status": "healthy",
            "model": probe.first_model_id,
            "payload": probe.payload,
        }

    def stop(self) -> None:
        """Stop the embedded rig if this was the last client."""
        from audiagentic.runtime.rig.registry import shutdown_rig_if_last
        if self.port > 0:
            shutdown_rig_if_last(port=self.port)


@contextmanager
def local_ai_tester(
    model_profile: str | None = None,
    model_file: str | None = None,
    port: int = 0,
    host: str = "127.0.0.1",
    api_key: str | None = None,
    timeout: float = 120.0,
    health_timeout: float = 60.0,
) -> Generator[LocalAITester, None, None]:
    """Start the embedded rig and yield a LocalAITester instance.

    Args:
        model_profile: Model profile name from rig config (e.g. "qwen2.5:3b").
        model_file: Path to GGUF model file (overrides model_profile).
        port: Port to use (0 = auto-select).
        host: Host to bind to.
        api_key: Optional API key for the endpoint.
        timeout: Request timeout for chat completions.
        health_timeout: Max seconds to wait for server health check.

    Yields:
        LocalAITester instance with base_url, model, port, and chat() method.

    Example:
        with local_ai_tester(model_profile="qwen3.5-2b") as tester:
            result = tester.chat("Hello")
            print(result.content)
    """
    from audiagentic.runtime.rig.embedded.launch import start_embedded_rig
    from audiagentic.runtime.rig.registry import register_client, shutdown_rig_if_last

    tester = LocalAITester(api_key=api_key, timeout=timeout)

    try:
        result = start_embedded_rig(
            model_profile=model_profile or "",
            port=port,
            host=host,
            model_file=model_file,
            health_timeout=health_timeout,
        )
        tester.base_url = result.base_url
        tester.model = result.model
        tester.port = result.port
        tester.pid = result.pid
        tester.endpoint = result.base_url

        register_client()

        yield tester

    finally:
        shutdown_rig_if_last(port=tester.port)


def create_async_tester(
    model_profile: str | None = None,
    model_file: str | None = None,
    port: int = 0,
    host: str = "127.0.0.1",
    api_key: str | None = None,
    timeout: float = 120.0,
    health_timeout: float = 60.0,
) -> LocalAITester:
    """Start the embedded rig synchronously and return a LocalAITester.

    Use this when you need the tester as a value (not a context manager),
    and manage lifecycle manually with tester.stop().

    Args:
        model_profile: Model profile name from rig config.
        model_file: Path to GGUF model file.
        port: Port to use (0 = auto-select).
        host: Host to bind to.
        api_key: Optional API key.
        timeout: Request timeout for chat completions.
        health_timeout: Max seconds to wait for health check.

    Returns:
        LocalAITester instance. Caller is responsible for calling stop().
    """
    from audiagentic.runtime.rig.embedded.launch import start_embedded_rig
    from audiagentic.runtime.rig.registry import register_client

    tester = LocalAITester(api_key=api_key, timeout=timeout)

    result = start_embedded_rig(
        model_profile=model_profile or "",
        port=port,
        host=host,
        model_file=model_file,
        health_timeout=health_timeout,
    )
    tester.base_url = result.base_url
    tester.model = result.model
    tester.port = result.port
    tester.pid = result.pid
    tester.endpoint = result.base_url

    register_client()

    return tester
