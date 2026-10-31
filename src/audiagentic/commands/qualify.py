"""``audiagentic qualify [PROVIDER] [--surface ID]`` (CFG07).

Proves the installed implementation of each selected provider session surface
on this machine and records the result as local qualification evidence, which
the surface resolver accepts for this platform. Writes only under the user
state directory. Exit codes: 0 every selected surface qualified, 2 at least
one failed, 3 unknown provider or surface.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

EXIT_FAILED = 2
EXIT_UNKNOWN = 3


def add_qualify_parsers(subparsers: Any) -> None:
    qualify = subparsers.add_parser(
        "qualify", help="Prove installed provider surfaces on this machine and record the evidence",
    )
    qualify.add_argument("provider", nargs="?", help="Provider id (default: every provider)")
    qualify.add_argument("--provider", dest="provider_option", metavar="ID", help="Same as the positional provider")
    qualify.add_argument("--surface", metavar="ID", help="Only this session surface")
    qualify.add_argument("--json", action="store_true", dest="as_json")


def run_qualify_command(args: argparse.Namespace) -> int:
    from audiagentic.components.providers.services.qualification.qualifier import qualify

    provider = args.provider_option or args.provider
    try:
        results = qualify(provider, args.surface)
    except KeyError as error:
        message = str(error.args[0])
        print(json.dumps({"error": message}) if args.as_json else f"qualify: {message}")
        return EXIT_UNKNOWN
    if args.as_json:
        print(json.dumps({"results": results}, indent=2))
    else:
        for item in results:
            print(f"{item['result']:9} {item['provider']}/{item['surface']} on {item['platform']}")
            for check in item["checks"]:
                print(f"          {'ok  ' if check['ok'] else 'FAIL'} {check['name']}: {check['detail']}")
        if not results:
            print("qualify: no session surfaces selected")
    return EXIT_FAILED if any(item["result"] != "qualified" for item in results) else 0
