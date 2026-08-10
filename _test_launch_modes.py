"""Test different launch modes for browser CDP."""

import os
import subprocess
import time
import urllib.request

port = 9227
browser = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
cmd = [browser, f"--remote-debugging-port={port}", "--no-first-run"]


def wait_cdp(port, timeout=20):
    for i in range(timeout * 2):
        time.sleep(0.5)
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
            if resp.status == 200:
                return True
        except Exception:
            pass
    return False


# Mode A: Plain (no flags)
print("Mode A: plain Popen...")
p = subprocess.Popen(
    cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)
ok = wait_cdp(port, 15)
print(f"  Result: {'OK' if ok else 'FAIL'} (PID {p.pid})")
if ok:
    os._exit(0)

# Kill it
try:
    p.terminate()
    p.wait(timeout=3)
except Exception:
    pass

port = 9228
cmd[1] = f"--remote-debugging-port={port}"

# Mode B: CREATE_NEW_PROCESS_GROUP only
print("Mode B: CREATE_NEW_PROCESS_GROUP...")
p = subprocess.Popen(
    cmd,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
ok = wait_cdp(port, 15)
print(f"  Result: {'OK' if ok else 'FAIL'} (PID {p.pid})")

try:
    p.terminate()
except Exception:
    pass
