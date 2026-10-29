"""``audiagentic agent list|show|add``: agent files (CFG05).

Adapter only: argument parsing and output. Agent semantics live in
``components/agents/configuration/agent_files.py``. ``list`` and ``show`` are
read-only; ``add`` writes one minimal agent file and nothing else.
Exit codes: 0 ok, 1 agent not found or already exists, 2 invalid agent
configuration, 3 discovery or write failure.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

EXIT_NOT_FOUND = 1
EXIT_INVALID = 2
EXIT_UNAVAILABLE = 3


def add_agent_parsers(subparsers: Any) -> None:
    agent = subparsers.add_parser("agent", help="List, show and add agent definitions")
    sub = agent.add_subparsers(dest="agent_cmd", required=True)
    listing = sub.add_parser("list", help="List resolved agents (read-only)")
    listing.add_argument("--json", action="store_true", dest="as_json")
    show = sub.add_parser("show", help="Show one resolved agent (read-only)")
    show.add_argument("agent_id")
    show.add_argument("--origin", action="store_true", help="Show which file set each field")
    show.add_argument("--json", action="store_true", dest="as_json")
    add = sub.add_parser("add", help="Write a minimal agent file")
    add.add_argument("agent_id")
    add.add_argument("--extends", dest="template", metavar="TEMPLATE")
    add.add_argument("--provider", required=True)
    add.add_argument("--model", required=True)
    add.add_argument("--surface")
    add.add_argument("--scope", choices=("user", "project"), default="user")
    add.add_argument("--json", action="store_true", dest="as_json")


def run_agent_command(args: argparse.Namespace) -> int:
    from audiagentic.components.agents.configuration import agent_files

    try:
        if args.agent_cmd == "add":
            return _add(args, agent_files)
        agents = agent_files.resolve_agents(project=args.project)
    except AudiaGenticError as error:
        return _fail(args, error)
    if args.agent_cmd == "list":
        rows = [{"id": agent.agent_id, "name": agent.fields.get("name", agent.agent_id),
                 "provider": agent.fields["provider"], "template": agent.template} for agent in agents.values()]
        if args.as_json:
            print(json.dumps(rows, indent=2))
        else:
            for row in rows:
                print(f"{row['id']:<28} {row['provider']:<12} {row['name']}"
                      + (f"  (extends {row['template']})" if row["template"] else ""))
        return 0
    agent = agents.get(args.agent_id)
    if agent is None:
        print(json.dumps({"found": False, "id": args.agent_id}) if args.as_json else f"{args.agent_id}: no such agent")
        return EXIT_NOT_FOUND
    if args.as_json:
        payload: dict[str, Any] = {"id": agent.agent_id, "template": agent.template, "fields": agent.fields,
                                   "files": [str(path) for path in agent.files]}
        if args.origin:
            payload["origins"] = {pointer: origin.describe() for pointer, origin in sorted(agent.origins.items())}
        print(json.dumps(payload, indent=2))
        return 0
    print(f"{agent.agent_id}" + (f" (extends {agent.template})" if agent.template else ""))
    for name, value in agent.fields.items():
        shown = value if not isinstance(value, str) or "\n" not in value else value.splitlines()[0] + " ..."
        origin = agent.origins.get(f"/{name}")
        print(f"  {name}: {json.dumps(shown)}" + (f"  # {origin.describe()}" if args.origin and origin else ""))
    return 0


def _add(args: argparse.Namespace, agent_files: Any) -> int:
    from audiagentic.foundation.config.settings import discover_project_root, project_config_dir
    from audiagentic.foundation.paths.home import user_config_dir

    if args.scope == "project":
        root = discover_project_root(args.project)
        if root is None:
            print("No project found; run inside a git checkout or pass --project")
            return EXIT_UNAVAILABLE
        directory = project_config_dir(root) / "agents"
    else:
        directory = user_config_dir() / "agents"
    path = directory / f"{args.agent_id}.yaml"
    if path.exists():
        print(json.dumps({"ok": False, "exists": str(path)}) if args.as_json else f"{path} already exists")
        return EXIT_NOT_FOUND
    lines = ["schema_version: 1"]
    if args.template:
        lines.append(f"extends: {args.template}")
    lines += [f"provider: {args.provider}", f"model: {json.dumps(args.model)}"]
    if args.surface:
        lines.append(f"surface: {args.surface}")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as error:
        print(f"Cannot write {path}: {error.strerror}")
        return EXIT_UNAVAILABLE
    try:
        agent_files.resolve_agents(project=args.project)
    except AudiaGenticError as error:
        path.unlink()
        return _fail(args, error)
    print(json.dumps({"ok": True, "file": str(path)}) if args.as_json else f"wrote {path}")
    return 0


def _fail(args: argparse.Namespace, error: AudiaGenticError) -> int:
    details = error.details or {}
    if args.as_json:
        print(json.dumps({"ok": False, "error-code": error.code, "message": error.message, "details": details}))
    else:
        where = details.get("file") or details.get("agent") or ""
        print(f"{error.code}: {error.message}" + (f" ({where})" if where else ""))
    unavailable = error.code in {"CFG-SET-001", "CFG-SET-005", "CFG-SET-006", "CFG-AGF-005"}
    return EXIT_UNAVAILABLE if unavailable else EXIT_INVALID


__all__ = ["add_agent_parsers", "run_agent_command"]
