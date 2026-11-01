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
    qualify.add_argument("--live", action="store_true",
                         help="Run the provider's native probes in a disposable environment and record evidence "
                              "(needs a provider; never runs by default)")
    qualify.add_argument("--json", action="store_true", dest="as_json")


def run_qualify_command(args: argparse.Namespace) -> int:
    from audiagentic.components.providers.services.qualification.qualifier import qualify

    provider = args.provider_option or args.provider
    if getattr(args, "live", False):
        return _run_live(provider, args.as_json)
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


def _run_live(provider: str | None, as_json: bool) -> int:
    from audiagentic.components.providers.services.qualification.live import qualify_live

    if not provider:
        print(json.dumps({"error": "--live needs a provider"}) if as_json else "qualify: --live needs a provider")
        return EXIT_UNKNOWN
    try:
        result = qualify_live(provider)
    except (KeyError, RuntimeError) as error:
        message = str(error.args[0])
        print(json.dumps({"error": message}) if as_json else f"qualify: {message}")
        return EXIT_UNKNOWN
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['state']:12} {result['provider']}/{result['surface']} (evidence {result['evidence-id']})")
        for name, proven in result["capabilities"].items():
            print(f"          {'ok  ' if proven else 'no  '} {name}")
        print(f"          reasons: {', '.join(result['reasons']) or 'none'}")
        print(f"          {result['claim']}")
    return 0 if result["state"] in ("supported", "partial") else EXIT_FAILED
