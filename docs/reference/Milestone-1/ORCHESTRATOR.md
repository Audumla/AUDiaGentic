# Orchestrator Instructions

## Mission

Implement the complete agent-session plan set in the order and gates defined by `IMPLEMENTATION.md`. The active plan file contains the executable scope. The old planning folder is not an implementation dependency.

## Authority order

1. `ARCHITECTURE.md`
2. `IMPLEMENTATION.md`
3. the active plan file
4. repository code and standards
5. `HARNESSES.md`
6. `DECISIONS.md`

Repository code may reveal that a named seam has moved or already landed. Reuse or migrate that seam; do not recreate a parallel abstraction. If code contradicts a non-negotiable architecture rule, stop and report the contradiction before implementation.

## Plan execution protocol

For each plan:

1. Confirm its dependencies and milestone gate.
2. Inspect every named code seam and search for equivalent existing implementations.
3. Characterize the current baseline with focused tests before changing it.
4. Split work only along independently testable contract, adapter, storage, or integration boundaries.
5. Require workers to report changed/deleted files, tests added, tests run, remaining risks, and any plan assumption invalidated by the code.
6. Integrate centrally and remove superseded paths in the same branch.
7. Run focused tests, architecture tests, relevant component suites, and required Windows/Linux/Docker proofs.
8. Update capability evidence and documentation only to the level actually proven.
9. Mark the plan complete only when every acceptance criterion passes.

## Worker prohibitions

Workers must not:

- create a second session store, lifecycle engine, evidence bus, capability registry, output selector, provider gateway, process manager, or recovery authority;
- expose ACP, Pi RPC, App Server, hook, plugin, CLI, SDK, or provider-native payload types through shared agents APIs;
- treat hooks/plugins as transport or lifecycle owners;
- infer completion from silence, process liveness, EOF, final-looking prose, resource inactivity, or control acknowledgement;
- select a transport because it is installed or automatically fall back to another surface;
- mutate a frozen session-surface/capability snapshot during a generation;
- parse or leak opaque provider session references outside the protected binding implementation;
- broaden contracts for hypothetical providers;
- retain compatibility aliases after all in-repository callers can migrate in the same change.

## Cross-plan invariants

Every implementation and review must prove:

- exactly one resolved surface and authoritative transport own a session generation;
- all lifecycle evidence enters through `AS19` contracts;
- `AS21` is the only normalized lifecycle/status projector;
- `AS31` is the only live-content owner and final-output selector;
- `AS29` is the sole provider session-surface declaration/resolution owner;
- `AS30` is the sole AG-to-provider binding/index owner;
- provider operations are exposed only through `providers_api`;
- unsupported and unvalidated capabilities fail deterministically without fallback;
- control acknowledgement never terminalizes or releases work;
- process signals use approved foundation process seams and never target unproven or external ownership;
- all public projections are redacted and project/context authorized.

## Milestone discipline

- PR1: `AS19`, `AS21`, `AS29`, `AS30`, `AS31` only.
- Pi and provider vertical slices begin only after PR1 is merged or fully present and green on the implementation branch.
- `AS46` is an orchestration parent; concrete named plans (`AS50`, `AS51`, `AS54`, `AS55`) take precedence where they overlap.
- A worker may not span milestone boundaries.

## Completion report

At every plan and PR boundary report:

- completed acceptance criteria;
- exact tests and platform/Docker evidence;
- obsolete code and plan paths removed;
- capability maturity changes;
- unresolved risks or blocked probes;
- exact next plan and dependency state;
- merge readiness.
