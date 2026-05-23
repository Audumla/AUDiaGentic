"""Execute generic follow-up action payloads."""
from __future__ import annotations

import argparse
import json
from typing import Any


def _resolve_handler(path: str):
    module_name, fn_name = path.rsplit(".", 1)
    module = __import__(module_name, fromlist=[fn_name])
    return getattr(module, fn_name)


def execute_follow_up(payload: dict[str, Any]) -> dict[str, Any]:
    kind = str(payload.get("kind") or "")
    if kind != "confirmable_handler_call":
        return {"ok": False, "error": f"unsupported follow-up kind: {kind}"}

    target = payload.get("target")
    if not isinstance(target, dict):
        return {"ok": False, "error": "follow-up target must be an object"}

    handler_path = target.get("handler")
    if not isinstance(handler_path, str) or "." not in handler_path:
        return {"ok": False, "error": "follow-up target.handler must be a dotted path"}

    kwargs = target.get("kwargs") or {}
    if not isinstance(kwargs, dict):
        return {"ok": False, "error": "follow-up target.kwargs must be an object"}

    handler = _resolve_handler(handler_path)
    result = handler(**kwargs)
    return {
        "ok": True,
        "kind": kind,
        "handler": handler_path,
        "result": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True, help="Follow-up payload as JSON")
    args = parser.parse_args()
    payload = json.loads(args.payload)
    print(json.dumps(execute_follow_up(payload), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

