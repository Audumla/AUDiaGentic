"""Tiny detached service fixture used by managed lifecycle integration tests."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def main() -> None:
    ready_path = Path(sys.argv[1])
    owner_epoch = os.environ["AUDIAGENTIC_SERVICE_OWNER_EPOCH"]
    temporary = ready_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"pid": os.getpid(), "owner-epoch": owner_epoch}), encoding="utf-8"
    )
    temporary.replace(ready_path)
    while True:
        time.sleep(0.1)


if __name__ == "__main__":
    main()
