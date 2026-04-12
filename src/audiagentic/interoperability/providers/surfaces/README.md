# interoperability/providers/surfaces/

## Purpose
Provider-facing surface definitions: the rendered instruction content, skill definitions, and tag surfaces that each provider receives. Separate from adapter execution wiring.

## Ownership
- `SkillDefinition` and surface base types
- Per-provider surface renderers (how skills and instructions are rendered for each provider's format)
- Surface registry (maps provider IDs to their renderer)

## Must NOT Own
- Provider execution/invocation (→ `adapters/`)
- Provider configuration loading (→ `foundation/config/`)
- Tag/alias definitions (→ `.audiagentic/prompt-syntax.yaml` + `execution/jobs/prompt_syntax.py`)

## Allowed Dependencies
- `foundation/contracts` — canonical types
- `foundation/config` — provider config for surface rendering

## Key Modules
| Module | Responsibility |
|--------|---------------|
| `base.py` | `SkillDefinition` dataclass and base surface interface |
| `registry.py` | Load and resolve the renderer registry by provider ID |
| `claude.py` | Claude-specific skill/surface rendering |
| `cline.py` | Cline-specific skill/surface rendering |
| `codex.py` | Codex-specific skill/surface rendering |
| `gemini.py` | Gemini-specific skill/surface rendering |
| `qwen.py` | Qwen-specific skill/surface rendering |
| `opencode.py` | opencode-specific skill/surface rendering |
| `copilot.py` | Copilot-specific skill/surface rendering |

## Relationship to adapters/
- **adapters/** = how to run a provider (execution wiring)
- **surfaces/** = what to show a provider (instruction content and skill definitions)
