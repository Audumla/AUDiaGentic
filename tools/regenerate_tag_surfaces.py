from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path
from typing import Any

import sys

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.execution.jobs.prompt_syntax import load_prompt_syntax


ACTION_ORDER = (
    "ag-plan",
    "ag-implement",
    "ag-review",
    "ag-audit",
    "ag-check-in-prep",
)

ACTION_DESCRIPTIONS = {
    "ag-plan": "Use for canonical @ag-plan launches. Shapes work before implementation.",
    "ag-implement": "Use for canonical @ag-implement launches. Carries out the requested change.",
    "ag-review": "Use for canonical @ag-review launches. Performs read-focused validation and completeness review without adding implementation work.",
    "ag-audit": "Use for canonical @ag-audit launches. Checks tracked docs, release artifacts, and state consistency.",
    "ag-check-in-prep": "Use for canonical @ag-check-in-prep launches. Prepares the repository for a stable check-in.",
}

ACTION_DO = {
    "ag-plan": [
        "map the requested change into a concrete execution plan",
        "identify dependencies, blockers, and review checkpoints",
        "keep the result deterministic and concise",
    ],
    "ag-implement": [
        "carry out the requested implementation work",
        "prefer shared helpers and repository-owned scripts",
        "preserve the tracked-doc and baseline contracts",
    ],
    "ag-review": [
        "perform read-focused validation and completeness review",
        "identify blockers, missing tests, and contract mismatches",
        "produce a deterministic review report",
    ],
    "ag-audit": [
        "audit tracked docs, release artifacts, and state consistency",
        "note drift, missing evidence, or stale references",
        "avoid implementation work unless explicitly asked",
    ],
    "ag-check-in-prep": [
        "prepare the repo for a stable check-in",
        "summarize outstanding changes and verification state",
        "keep the output concise and action-oriented",
    ],
}

ACTION_DONT = {
    "ag-plan": [
        "do not implement the requested change",
        "do not mutate tracked docs without approval",
    ],
    "ag-implement": [
        "do not broaden scope beyond the requested change",
        "do not rewrite contracts without change control",
    ],
    "ag-review": [
        "do not add implementation work unless explicitly asked",
        "do not broaden review into feature-scope changes",
    ],
    "ag-audit": [
        "do not mutate tracked docs without approval",
        "do not hide drift behind vague summaries",
    ],
    "ag-check-in-prep": [
        "do not change implementation behavior",
        "do not broaden into feature work",
    ],
}


def _nowrite(path: Path, text: str, *, dry_run: bool, check: bool, diffs: list[str]) -> None:
    if path.exists():
        current = path.read_text(encoding="utf-8")
        if current == text:
            return
        diffs.append(str(path))
        if check:
            return
    else:
        diffs.append(str(path))
        if check:
            return

    if dry_run:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _legacy_action_name(tag: str) -> str:
    return tag.removeprefix("ag-")


def _canonical_tags(syntax: dict[str, Any]) -> list[str]:
    tags = syntax.get("canonical-tags")
    if isinstance(tags, list):
        return [tag for tag in tags if isinstance(tag, str) and tag]
    return list(ACTION_ORDER)


def _tag_alias_examples(syntax: dict[str, Any]) -> list[str]:
    aliases = syntax.get("tag-aliases")
    if not isinstance(aliases, dict):
        return []
    preferred_order = ["agp", "agi", "agr", "aga", "agc"]
    examples = []
    for alias in preferred_order:
        target = aliases.get(alias)
        if isinstance(target, str):
            examples.append(f"- `{alias}` -> `{target}`")
    return examples


def _provider_alias_examples(syntax: dict[str, Any]) -> list[str]:
    aliases = syntax.get("provider-aliases")
    if not isinstance(aliases, dict):
        return []
    preferred_order = ["cx", "cld", "cln", "gm", "cp"]
    examples = []
    for alias in preferred_order:
        target = aliases.get(alias)
        if isinstance(target, str):
            examples.append(f"- `{alias}` -> `{target}`")
    return examples


def _render_skill(tag: str, *, root_label: str) -> str:
    legacy_name = _legacy_action_name(tag)
    description = ACTION_DESCRIPTIONS[tag]
    do_lines = "\n".join(f"- {item}" for item in ACTION_DO[tag])
    dont_lines = "\n".join(f"- {item}" for item in ACTION_DONT[tag])
    return (
        "---\n"
        f"name: {tag}\n"
        f"description: {description}\n"
        "---\n\n"
        f"# {tag} skill\n\n"
        f"Use this skill for canonical `@{tag}` launches.\n\n"
        "Trigger:\n"
        f"- first non-empty line resolves to `{tag}` or the backward-compatible `{legacy_name}` alias\n\n"
        "Do:\n"
        f"{do_lines}\n\n"
        "Do not:\n"
        f"{dont_lines}\n\n"
        f"Root surface: `{root_label}`\n"
    )


def _render_agents_md(syntax: dict[str, Any]) -> str:
    canonical_tags = _canonical_tags(syntax)
    tag_examples = "\n".join(_tag_alias_examples(syntax))
    provider_examples = "\n".join(_provider_alias_examples(syntax))
    canonical_lines = "\n".join(f"- `@{tag}`" for tag in canonical_tags)
    return (
        "# AGENTS.md\n\n"
        "This repository uses canonical prompt tags to launch AUDiaGentic workflow jobs.\n\n"
        "## Canonical rule\n\n"
        f"- Do not reinterpret {', '.join(f'`@{tag}`' for tag in canonical_tags)}.\n"
        "- Route the raw tagged prompt through the repo-owned bridge instead of inventing a separate\n"
        "  workflow semantics layer.\n"
        "- Keep provenance visible: provider id, surface, and session id should survive normalization.\n"
        "- Canonical names are config-managed in `.audiagentic/prompt-syntax.yaml`; run\n"
        "  `python tools/regenerate_tag_surfaces.py --project-root .` after renaming tags or aliases.\n\n"
        "## Prompt-calling protocol\n\n"
        "If a prompt begins with a canonical tag, treat it as a workflow launch request, not ordinary\n"
        "chat.\n\n"
        "## Bridge mechanics\n\n"
        "The bridge is the execution boundary for tagged prompts.\n\n"
        "- Read the raw tagged prompt, including the first non-empty line and the prompt body.\n"
        "- Normalize the tag, provider shorthand, and argument aliases using\n"
        "  `.audiagentic/prompt-syntax.yaml`.\n"
        "- Preserve provenance fields through normalization: provider id, surface, and session id.\n"
        "- Apply project defaults when the prompt omits `id`, `context`, `output`, or `template`.\n"
        "- Treat the canonical action tags as workflow selectors, not as free-form instructions:\n"
        f"{canonical_lines}\n"
        "- Treat provider shorthands as provider selectors that still route through the same normalized\n"
        "  launch contract.\n"
        "- If the prompt is tagged but no explicit subject is supplied, let the bridge create the default\n"
        "  generic subject/job identity rather than inventing ad hoc semantics.\n"
        "- Stream or capture provider output through AUDiaGentic-owned runtime artifacts; the provider\n"
        "  should not own persistence policy.\n\n"
        "The Codex launch path is:\n\n"
        "```powershell\n"
        "python tools/codex_prompt_trigger_bridge.py --project-root .\n"
        "```\n\n"
        "The shared bridge normalizes the raw prompt and forwards it into `prompt-launch`, so the\n"
        "tagged prompt becomes a job request with preserved provenance and project defaults.\n\n"
        "## Codex path\n\n"
        "Codex should use the shared prompt-trigger bridge:\n\n"
        "```powershell\n"
        "python tools/codex_prompt_trigger_bridge.py --project-root .\n"
        "```\n\n"
        "If a hook or instruction surface is partial, fall back to the bridge and keep the shared launch\n"
        "grammar unchanged.\n\n"
        "## Standard prompt shape\n\n"
        "Prefer the short, defaults-first form:\n\n"
        "```text\n"
        "@ag-review provider=codex id=job_001 ctx=documentation t=review-default\n"
        "Review the current project state and call out any gaps.\n"
        "```\n\n"
        "When a provider/tag default template exists under `.audiagentic/prompts/<tag>/`, the shortest\n"
        "form is also valid:\n\n"
        "```text\n"
        "@ag-review\n"
        "```\n\n"
        "In that case the bridge should:\n"
        "- resolve the provider from the suffix\n"
        "- load the provider or shared default template\n"
        "- create the default job/subject identity if none is supplied\n"
        "- preserve provenance through normalization\n\n"
        "The bridge should accept the long-form canonical names as well:\n\n"
        "- `provider`\n"
        "- `id`\n"
        "- `context`\n"
        "- `output`\n"
        "- `template`\n\n"
        "and the common aliases:\n\n"
        "- `ctx` -> `context`\n"
        "- `out` -> `output`\n"
        "- `t` -> `template`\n\n"
        "## Tag and provider aliases\n\n"
        "Centralized in `.audiagentic/prompt-syntax.yaml`. Available shortcuts:\n\n"
        f"{tag_examples}\n"
        f"{provider_examples}\n\n"
        "## Skills\n\n"
        "Each canonical action maps to a focused skill under `.agents/skills/`:\n\n"
        + "\n".join(f"- `{tag}`" for tag in canonical_tags)
        + "\n\n"
        "## Review doctrine\n\n"
        "- review prompts should stay read-focused unless the normalized request explicitly allows more\n"
        "- do not broaden review into implementation work\n"
        "- keep tracked docs and release artifacts synchronized with the job record\n"
    )


def _render_claude_md(syntax: dict[str, Any]) -> str:
    canonical_tags = _canonical_tags(syntax)
    tag_examples = "\n".join(_tag_alias_examples(syntax))
    provider_examples = "\n".join(_provider_alias_examples(syntax))
    canonical_lines = "\n".join(f"- {tag}" for tag in canonical_tags)
    return (
        "# CLAUDE.md\n\n"
        "This repository uses canonical prompt tags to launch AUDiaGentic workflow jobs.\n\n"
        "## Canonical rule\n\n"
        f"- Do not reinterpret {', '.join(f'`@{tag}`' for tag in canonical_tags)}.\n"
        "- Route the raw tagged prompt through the repo-owned bridge instead of inventing a separate\n"
        "  workflow semantics layer.\n"
        "- Keep provenance visible: provider id, surface, and session id should survive normalization.\n"
        "- Canonical names are config-managed in `.audiagentic/prompt-syntax.yaml`; run\n"
        "  `python tools/regenerate_tag_surfaces.py --project-root .` after renaming tags or aliases.\n\n"
        "## Bridge\n\n"
        "When a Claude prompt begins with a canonical tag, use the shared prompt-trigger bridge:\n\n"
        "```powershell\n"
        "python tools/claude_prompt_trigger_bridge.py --project-root .\n"
        "```\n\n"
        "If a hook surface is available, `UserPromptSubmit` should hand the raw prompt to the bridge\n"
        "before planning starts. If the hook surface is partial, fall back to the bridge and keep the\n"
        "shared launch grammar unchanged.\n\n"
        "## Tag shortcuts and aliases\n\n"
        "Tag and provider aliases are centralized in `.audiagentic/prompt-syntax.yaml` and work in all surfaces:\n\n"
        "Canonical tags:\n\n"
        f"{canonical_lines}\n\n"
        f"{tag_examples}\n\n"
        f"{provider_examples}\n\n"
        "All of these are equivalent:\n\n"
        "```text\n"
        "@ag-review provider=cline\n"
        "@agr provider=cline\n"
        "@review provider=cline\n"
        "@r provider=cline\n"
        "@ag-review-cline\n"
        "@r-cline\n"
        "```\n\n"
        "## Review doctrine\n\n"
        "- review prompts should stay read-focused unless the normalized request explicitly allows more\n"
        "- do not broaden review into implementation work\n"
        "- keep tracked docs and release artifacts synchronized with the job record\n"
    )


def _render_clinerules_prompt_tags_md(syntax: dict[str, Any]) -> str:
    canonical_tags = _canonical_tags(syntax)
    tag_examples = "\n".join(_tag_alias_examples(syntax))
    provider_examples = "\n".join(_provider_alias_examples(syntax))
    canonical_lines = "\n".join(f"- `@{tag}`" for tag in canonical_tags)
    return (
        "# Prompt tag doctrine\n\n"
        "Canonical tags:\n\n"
        f"{canonical_lines}\n\n"
        "Rules:\n\n"
        "- parse only the first non-empty line for the canonical tag\n"
        "- keep tag semantics identical to the shared AUDiaGentic launch contract\n"
        "- do not invent provider-specific alternate tags\n"
        "- preserve raw prompt text in provenance metadata\n"
        "- route tagged prompts through the shared bridge when a native hook path is not stable\n"
        "- canonical names are config-managed in `.audiagentic/prompt-syntax.yaml`; run\n"
        "  `python tools/regenerate_tag_surfaces.py --project-root .` after renaming tags or aliases\n\n"
        "## Tag aliases and shortcuts\n\n"
        "Centralized in `.audiagentic/prompt-syntax.yaml`. All of these are equivalent:\n\n"
        f"{tag_examples}\n\n"
        f"{provider_examples}\n\n"
        "Use shortcuts for brevity:\n\n"
        "```text\n"
        "@agr-cln target=packet:PKT-PRV-033\n"
        "Review the implementation status.\n"
        "```\n"
    )


def _render_skill_manifest(tag: str) -> str:
    return _render_skill(tag, root_label=f".agents/skills/{tag}/SKILL.md")


def _render_claude_skill(tag: str) -> str:
    return _render_skill(tag, root_label=f".claude/skills/{tag}/SKILL.md")


def _render_legacy_skill(tag: str) -> str:
    return _render_skill(tag, root_label=f"legacy compatibility surface for `{tag}`")


def _surface_map(syntax: dict[str, Any]) -> dict[Path, str]:
    surfaces: dict[Path, str] = {
        ROOT / "AGENTS.md": _render_agents_md(syntax),
        ROOT / "CLAUDE.md": _render_claude_md(syntax),
        ROOT / ".clinerules" / "prompt-tags.md": _render_clinerules_prompt_tags_md(syntax),
        ROOT / ".claude" / "rules" / "prompt-tags.md": _render_clinerules_prompt_tags_md(syntax),
    }
    for tag in _canonical_tags(syntax):
        legacy_name = _legacy_action_name(tag)
        surfaces[ROOT / ".agents" / "skills" / tag / "SKILL.md"] = _render_skill_manifest(tag)
        surfaces[ROOT / ".claude" / "skills" / tag / "SKILL.md"] = _render_claude_skill(tag)
        surfaces[ROOT / ".agents" / "skills" / legacy_name / "SKILL.md"] = _render_legacy_skill(tag)
        surfaces[ROOT / ".claude" / "skills" / legacy_name / "SKILL.md"] = _render_legacy_skill(tag)
    return surfaces


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="regenerate_tag_surfaces")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    project_root = Path(args.project_root).resolve()
    syntax = load_prompt_syntax(project_root)
    surfaces = _surface_map(syntax)
    diffs: list[str] = []

    for path, text in surfaces.items():
        if path.exists():
            current = path.read_text(encoding="utf-8")
            if current == text:
                continue
        diffs.append(str(path.relative_to(project_root)))
        if not args.check and not args.dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_path, path)
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

    if args.check:
        if diffs:
            print("Tag surface regeneration check failed:")
            for item in diffs:
                print(f"- {item}")
            return 1
        print("Tag surface regeneration check passed.")
        return 0

    if args.dry_run:
        if diffs:
            print("Tag surface regeneration dry run:")
            for item in diffs:
                print(f"- {item}")
        else:
            print("Tag surface regeneration dry run: no changes.")
        return 0

    if diffs:
        print("Tag surface regeneration wrote:")
        for item in diffs:
            print(f"- {item}")
    else:
        print("Tag surface regeneration: no changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
