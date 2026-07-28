# Recipe upgrade inventory

Status: PR09 audit baseline, 2026-07-28. This records whether the existing
recipe mechanisms can expose the explicit `upgrade` lifecycle. `upgrade` is
never inferred from `apply`, and no entry below authorizes launch-time updates.

| Existing mechanism | Classification | Upgrade route / constraint |
| --- | --- | --- |
| `hindsight-aider` | package-owned | `pip`-managed wrapper; add only after a pinned desired version and installed-version probe exist. |
| `hindsight-codex`, `hindsight-copilot`, `hindsight-pi`, `hindsight-roo`, `hindsight-openhands` | configuration-only | Not applicable: recipes project Hindsight-owned integration/configuration, not an owned versioned provider binary. |
| `hindsight-managed-mcp`, `hindsight-managed-mcp-stdio`, `hindsight-plugin` | configuration-only | Not applicable: managed entry reconciliation is already apply/prune, not dependency replacement. |
| Provider npm CLI declarations: `claude`, `cline`, `codex`, `continue`, `copilot`, `gemini`, `opencode`, `qwen` | package-manager-owned | Candidate for delegated npm upgrade after each descriptor gains a desired version/provenance and a resolved installed-version probe. Do not treat `@latest` as an upgrade target. |
| Provider uv CLI declarations: `aider`, `openhands` | package-manager-owned | Candidate for delegated uv/pip upgrade with the same desired-version and post-upgrade probe requirements. |
| Provider brew CLI declaration: `plandex` | package-manager-owned | Candidate only on supported host/package-manager combinations; package/repository identity must be recorded. |
| Provider VS Code declaration: `roo` | external-managed | Not applicable until extension version and user/global scope ownership are proven. |
| Provider callable declaration: `pi` | component-owned | Requires a separate Pi harness version/provenance contract; do not derive it from prompt/template materialization. |
| Provider script declarations: `antigravity`, `goose` | unsafe/unverified | Not applicable. Their mutable `curl | shell` sources must be replaced by pinned verified installers before upgrade support is considered. |
| `local_openai` | no artifact | Not applicable: it is a connector declaration with no CLI installer. |
| Fixtures: `npm-cli`, `lsp-pyright`, `hindsight-codex` | contract fixture | Update only to prove schema/mode compatibility; they do not define production update policy. |
| PR08 llama.cpp rig | owned binary artifact | First full upgrade consumer: config-owned pinned manifest, checksum verification, staged activation, provenance, and explicit upgrade action. |

## Shared admission criteria

An entry may opt in only when it has all of:

1. an owned artifact or a package manager with explicit ownership;
2. a declared desired version/provenance, not mutable `latest`;
3. a non-mutating installed-version probe;
4. a verified post-upgrade probe; and
5. a safe rollback or a documented package-manager recovery path.

Otherwise it returns the canonical `not-applicable` upgrade result. This is a
deliberate classification, not missing implementation.
