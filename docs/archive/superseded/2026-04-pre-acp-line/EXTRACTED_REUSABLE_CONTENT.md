# Extracted Reusable Content

Before archiving the pre-ACP line, the following reusable ideas were intentionally retained at the conceptual level:

## Reusable guidance retained

- smoke-test guidance for provider bridges and prompt-trigger surfaces
- managed-surface generation ideas where the repo owns generated provider-facing prompt assets
- runtime artifact ownership expectations, especially that providers should not own persistence
- preflight validation ideas for repo-local provider surfaces and required assets
- repo-local asset validation patterns for bridge launchers and generated prompt surfaces

## Where those ideas remain active

- active provider/bridge direction in the remaining provider docs and implementation pack
- active contracts around runtime artifacts, prompt launch, stream capture, and input capture
- active managed-surface and prompt-syntax work already present in the repository

## Not retained as active doctrine

- Discord-specific delivery assumptions
- Continue-specific wrapper/config doctrine
- local-openai-specific bridge doctrine as an active first-class rollout line
- packet lines that bundled Qwen with local-openai in a way that now obscures current scope
