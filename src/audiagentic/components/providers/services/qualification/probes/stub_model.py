"""A deterministic local stand-in for a model endpoint, used only by disposable qualification probes.

It speaks just enough of the OpenAI Responses streaming protocol for a harness to complete a real turn:
every request gets ``STUB-REPLY-<n>`` where ``n`` is the request's ordinal. A gate lets a probe hold a
response open (a deterministic busy window, no sleeps) and release it. It binds loopback on an OS-assigned
port, records only counts (never request bodies), and notes any request other than ``POST /v1/responses`` so a
probe can fail closed if the harness reaches for anything else. Evidence produced with it is protocol
evidence: it says nothing about a real model.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class StubModel:
    def __init__(self) -> None:
        self._gate = threading.Event()
        self._gate.set()
        self._lock = threading.Condition()
        self.requests = 0
        self.input_items: list[int] = []
        self.unexpected: list[str] = []
        self._httpd: ThreadingHTTPServer | None = None

    @property
    def base_url(self) -> str:
        assert self._httpd is not None
        return f"http://127.0.0.1:{self._httpd.server_address[1]}/v1"

    def start(self) -> StubModel:
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: object) -> None:  # silence request logging
                pass

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
                length = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(length)
                if self.path != "/v1/responses":
                    stub._note_unexpected(f"POST {self.path}")
                    self.send_response(404)
                    self.send_header("content-length", "0")
                    self.end_headers()
                    return
                try:
                    items = len(json.loads(body or b"{}").get("input") or [])
                except ValueError:
                    items = -1
                ordinal = stub._count(items)
                text = f"STUB-REPLY-{ordinal}"
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-cache")
                self.send_header("connection", "close")
                self.end_headers()
                message = {"type": "message", "id": f"msg_{ordinal}", "role": "assistant", "status": "completed",
                           "content": [{"type": "output_text", "text": text}]}
                part = {"type": "output_text", "text": "", "annotations": []}
                events = [
                    ("response.created", {"response": {"id": f"resp_{ordinal}", "object": "response",
                                                       "status": "in_progress", "output": []}}),
                    ("response.output_item.added", {"output_index": 0, "item": {**message, "status": "in_progress",
                                                                               "content": []}}),
                    ("response.content_part.added", {"item_id": message["id"], "output_index": 0, "content_index": 0,
                                                     "part": part}),
                ]
                self._send(events)
                stub._gate.wait(60)  # a held gate keeps this turn demonstrably active
                done = {"item_id": message["id"], "output_index": 0, "content_index": 0}
                self._send([
                    ("response.output_text.delta", {**done, "delta": text}),
                    ("response.output_text.done", {**done, "text": text}),
                    ("response.content_part.done", {**done, "part": {**part, "text": text}}),
                    ("response.output_item.done", {"output_index": 0, "item": message}),
                    ("response.completed", {"response": {
                        "id": f"resp_{ordinal}", "object": "response", "status": "completed", "output": [message],
                        "usage": {"input_tokens": 1, "input_tokens_details": {"cached_tokens": 0},
                                  "output_tokens": 1, "output_tokens_details": {"reasoning_tokens": 0},
                                  "total_tokens": 2}}}),
                ], start=3)

            def do_GET(self) -> None:  # noqa: N802
                stub._note_unexpected(f"GET {self.path}")
                self.send_response(404)
                self.send_header("content-length", "0")
                self.end_headers()

            def _send(self, events: list[tuple[str, dict]], start: int = 0) -> None:
                for offset, (name, data) in enumerate(events):
                    payload = {"type": name, "sequence_number": start + offset, **data}
                    try:
                        self.wfile.write(f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode())
                        self.wfile.flush()
                    except OSError:
                        return  # the harness went away mid-stream

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self.release()
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def _count(self, items: int) -> int:
        with self._lock:
            self.requests += 1
            self.input_items.append(items)
            self._lock.notify_all()
            return self.requests

    def _note_unexpected(self, what: str) -> None:
        with self._lock:
            self.unexpected.append(what)

    def hold(self) -> None:
        """Responses started from now on stay open until ``release``."""
        self._gate.clear()

    def release(self) -> None:
        self._gate.set()

    def wait_for_requests(self, count: int, timeout: float) -> bool:
        with self._lock:
            return self._lock.wait_for(lambda: self.requests >= count, timeout)

    def write_config(self, codex_home: Path, workspace: Path) -> None:
        """Point the harness at this stub in the disposable CODEX_HOME; no OpenAI sign-in is needed."""
        (codex_home / "config.toml").write_text(
            'model = "stub-model"\nmodel_provider = "stub"\napproval_policy = "never"\nsandbox_mode = "read-only"\n'
            "[model_providers.stub]\n"
            'name = "Stub"\n'
            f'base_url = "{self.base_url}"\n'
            'wire_api = "responses"\n'
            "requires_openai_auth = false\n"
            f'[projects."{workspace}"]\n'
            'trust_level = "trusted"\n', encoding="utf-8")
