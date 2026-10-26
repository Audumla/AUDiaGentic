"""Independent native qualification client; never reads server workspace files."""

import argparse
import json
import ssl
import sys
import time
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("package", type=Path)
    p.add_argument("base", type=Path)
    p.add_argument("endpoint")
    p.add_argument("principal")
    p.add_argument("action", choices=["submit", "observe"])
    p.add_argument("--request-id")
    args = p.parse_args()
    sys.path.insert(0, str(args.package))
    from audiagentic.components.agents.gateway.remote_client import StandaloneGatewayClient
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    config = json.loads((args.base / "client-config.json").read_text())
    c = StandaloneGatewayClient(
        args.endpoint,
        (args.base / (args.principal + ".token")).read_text(),
        shared_server_id=config["server-id"],
        shared_project_id=args.principal,
        logical_client_id="qualification:" + args.principal,
        ssl_context=ssl.create_default_context(cafile=str(args.base / "cert.pem")),
        request_timeout=10,
    )
    try:
        if args.action == "submit":
            try:
                result = c.submit_execution_request(
                    args.base / "client-unrelated",
                    execution_profile_id=config["execution-profile-id"],
                    prompt_body="Read qualification-input.txt from your working directory. Reply with exactly its content. Do not edit files or run any other task.",
                    session_keep_alive=False,
                    metadata={"idempotency_key": "live-file-check"},
                )
                print(json.dumps({k: result.get(k) for k in ("request-id", "session-id", "state")}))
            except AudiaGenticError as e:
                print(json.dumps({"error-code": e.code}))
                sys.exit(3)
        else:
            deadline = time.monotonic() + 180
            while True:
                status = c.get_execution_request(args.base / "client-unrelated", args.request_id)
                if status.get("lifecycle") == "terminal":
                    result = {"status": status}
                    try:
                        result["response"] = c.get_execution_response(args.base, args.request_id)
                    except AudiaGenticError as e:
                        result["error-code"] = e.code
                    print(json.dumps(result))
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError("bounded qualification observation expired")
                time.sleep(2)
    finally:
        c.close()


if __name__ == "__main__":
    main()
