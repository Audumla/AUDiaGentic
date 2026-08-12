"""Repository-owned controllable provider used by SH22 integration gates."""
from __future__ import annotations

import os
import sys
import time


def main() -> int:
    prompt = sys.stdin.read() or ""
    if os.environ.get("AUDIAGENTIC_ACTIVITY_RIG_PAUSE") == "1":
        time.sleep(float(os.environ.get("AUDIAGENTIC_ACTIVITY_RIG_PAUSE_SECONDS", "1")))
    if os.environ.get("AUDIAGENTIC_ACTIVITY_RIG_STALL") == "1":
        time.sleep(float(os.environ.get("AUDIAGENTIC_ACTIVITY_RIG_STALL_SECONDS", "30")))
    sys.stdout.write("ACTIVITY_RIG_OK:" + prompt[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
