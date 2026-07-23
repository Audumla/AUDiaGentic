# Agent Session Architecture

## Ownership model

A logical AUDiaGentic session generation resolves exactly one provider session surface and one authoritative transport before launch. The resolved surface and capability snapshot are immutable for that generation.

The transport owns native execution mechanics:

- open/attach/resume execution where declared;
- prompt dispatch;
- provider-native cancellation/control submission;
- protocol/process connection lifetime;
- provider session reference returned by the surface;
- deterministic close/detach behavior.

Agents owns:

- queueing and FIFO;
- AUDiaGentic session/request/turn identity;
- durable session records and bindings;
- lifecycle projection and public status;
- user-content persistence and final-output selection;
- authorization and external API behavior.

Providers own:

- exact surface/version/platform declarations;
- transport construction and protocol mapping;
- provider-native ref validation and capability operations;
- hook/plugin/config reconciliation through existing provider families;
- probe evidence and provider-specific adapters.

Foundation owns provider-neutral contracts and reusable process/filesystem mechanics.

## Surface and capability truth

Capabilities belong to a concrete surface, not a provider name. Pi RPC and Pi ACP, Codex ACP and Codex App Server, and CLI/SDK/editor surfaces are independent until identity and capability equivalence are proven.

`AS29 session_surfaces` is the sole runtime declaration owner. A descriptor declaration is necessary but not sufficient: exact version/platform probes and registered implementations determine effective support. Candidate documentation never activates runtime behavior.

Selection is explicit. Installed-first selection, automatic fallback, name similarity, “latest” session selection, UI scraping, and runtime transport switching are prohibited.

## Evidence, lifecycle, and status

Provider-native frames remain inside provider/foundation adapters. They become bounded provider-neutral `TransportObservation` values, then validated correlated `StatusEvidence`. Hooks, plugins, process facts, and native subscriptions are observers only.

`AS21` projects evidence into lifecycle decisions and layered status snapshots. Evidence conflicts lower confidence; they are not majority-voted. Process alive is not turn active. Prompt returned is not provider settled. A control acknowledgement is not terminal evidence. Durable SH07 terminal facts outrank ephemeral decisions for public terminal outcome.

Lifecycle and outcome remain separate. Lifecycle is a small stable vocabulary such as pending, active, waiting, completing, available, terminal, and unknown. Failed, cancelled, interrupted, timed-out, rejected, and similar values are outcomes or reasons, not competing lifecycle states.

## Content and final output

User assistant text uses the separate `AS31` content lane. It never flows through lifecycle evidence, diagnostic events, operational records, timelines, tool metadata, or raw provider payload persistence. Hidden reasoning and raw tool arguments/results are excluded.

`AS31` owns coalescing, correlation, retention, cursor/gap behavior, storage recovery, and final-output selection. Content delivery failure degrades content only and never controls or terminalizes the turn.

## Durable bindings

`AS30` owns the protected AUDiaGentic-session-generation to provider-session/thread binding. An opaque provider reference may be recorded after open, but recording it grants no attach, resume, discovery, sharing, or replacement right. Each operation requires validated support from the frozen `AS29` surface and matching identity, project, and execution context.

Raw provider refs never appear in ordinary logs, events, metrics, paths, filenames, or public status. Recovery rebuilds from validated AUDiaGentic records; it does not discover external provider sessions implicitly.

## Process lifecycle and isolation

Reuse `foundation/system/process.py`, `supervised_process.py`, `adopted_process.py`, `StartupLock`, atomic file helpers, and existing shared-service lifecycle seams. No second process framework is permitted.

Owned/adopted children require identity-safe observation and stop. External processes are never signalled. Windows hard-parent-death claims require Job Object proof. POSIX claims are limited to proven graceful/exception cleanup and next-start reconciliation unless a stronger supervisor is actually implemented and tested.

Provider runtime isolation must prove unique runtime/config/session paths, no global mutable state access, child lifetime ownership, cleanup on every exit path, restart recovery, and simultaneous-request non-contamination.

## Migration rule

When a canonical seam replaces an old path:

1. characterize current behavior;
2. add the canonical contract/adapter;
3. migrate every caller and fixture;
4. add architecture/grep/AST gates;
5. delete the obsolete path in the same implementation window.

Permanent parallel paths and internal-only compatibility shims are prohibited unless an external compatibility contract requires them.
