import inspect
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from audiagentic.components.providers.adapters.opencode.join import OpenCodeClient


def test_prompt_always_sends_queue_delivery_and_offers_no_other_mode():
    seen: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):  # noqa: N802
            seen.append(json.loads(self.rfile.read(int(self.headers["content-length"]))))
            body = json.dumps({"data": {"id": "msg_x"}}).encode()
            self.send_response(200)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = OpenCodeClient(server.server_port, "pw")
        client.prompt("ses_example_1", "hi", message_id="msg_x")
        client.prompt("ses_example_1", "again")
        assert [body["delivery"] for body in seen] == ["queue", "queue"]
        assert "delivery" not in inspect.signature(OpenCodeClient.prompt).parameters
    finally:
        server.shutdown()
        server.server_close()
