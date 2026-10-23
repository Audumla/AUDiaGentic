"""Bound ACP waits by elapsed time, not the number of valid notifications."""
import json
import queue
import threading
import time
from collections import deque


def read_acp_response(proc, response_id, answer_request, *, timeout=300):
    """Return (response, stop reason, bounded tail) without a frame-count cutoff."""
    lines = queue.Queue(maxsize=64)
    stopped = threading.Event()

    def read():
        while not stopped.is_set():
            line = proc.stdout.readline()
            while not stopped.is_set():
                try:
                    lines.put(line, timeout=0.05)
                    break
                except queue.Full:
                    continue
            if not line:
                return

    threading.Thread(target=read, daemon=True).start()
    deadline = time.monotonic() + timeout
    tail = deque(maxlen=10)
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, "deadline", list(tail)
            try:
                line = lines.get(timeout=remaining)
            except queue.Empty:
                return None, "deadline", list(tail)
            if not line:
                return None, "eof", list(tail)
            message = json.loads(line)
            tail.append(message)
            if answer_request(proc, message):
                continue
            if message.get("id") == response_id and "method" not in message:
                return message, "response", list(tail)
    finally:
        stopped.set()
