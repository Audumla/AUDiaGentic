import io
import json
import threading
from types import SimpleNamespace

from tests.integration.providers.acp_io import read_acp_response


def test_more_than_4000_frames_and_duplex_request_do_not_end_a_turn():
    messages = [{"method": "session/update", "params": {"sequence": i}} for i in range(4500)]
    messages += [{"id": 3, "method": "session/request_permission"}, {"id": 3, "result": {"stopReason": "end_turn"}}]
    proc = SimpleNamespace(stdout=io.BytesIO(b"\n".join(json.dumps(m).encode() for m in messages)))
    answered = []
    def answer(proc, message):
        if message.get("method") == "session/request_permission":
            answered.append(message)
            return True
        return False
    result, reason, tail = read_acp_response(proc, 3, answer, timeout=2)
    assert reason == "response" and result["result"]["stopReason"] == "end_turn"
    assert len(answered) == 1 and len(tail) == 10


def test_eof_is_distinct_from_deadline():
    assert read_acp_response(SimpleNamespace(stdout=io.BytesIO()), 3, lambda *_: False)[1] == "eof"
    release = threading.Event()
    class Silent:
        def readline(self):
            release.wait(2)
            return b""
    try:
        result = read_acp_response(SimpleNamespace(stdout=Silent()), 3, lambda *_: False, timeout=0.02)
        assert result[1] == "deadline"
    finally:
        release.set()
