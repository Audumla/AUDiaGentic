import json
import subprocess
import time
import urllib.request

port = 9225
browser = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
cmd = [browser, f"--remote-debugging-port={port}", "--no-first-run"]

# Non-detached launch
proc = subprocess.Popen(cmd)
print(f"PID: {proc.pid}")

for i in range(20):
    time.sleep(1)
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3)
        if resp.status == 200:
            data = json.loads(resp.read().decode())
            print(f"CDP ready! Browser: {data.get('Browser')}")
            break
    except Exception:
        pass
else:
    print("CDP failed")
