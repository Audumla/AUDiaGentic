# gpt-auto adapter

The gateway owns durable AUDiaGentic sessions. One project-scoped
`GptAutoProviderRuntime` owns a shared Brave/CDP connection and concurrent
Puppeteer bridge. Each gateway session owns a `PersistentChat`; its page handle
is volatile and its ChatGPT `/c/<id>` binding is durably installed through the
gateway after the first accepted turn.

Runtime policy lives only in `.audiagentic/config/providers/gpt-auto.yaml`.
The contract is strict: unknown or legacy keys fail instead of being aliased.

Important invariants:

- Gateway ID, ChatGPT conversation ID, request ID, and page handle are distinct.
- page handles and browser process facts are never durable session identity.
- one browser/helper serves many chats; closing one chat does not stop either.
- positive user-message evidence is required before a turn is `submitted`.
- response workflow transitions are driven by configured named DOM signals and
  declarative evidence policies, not selectors embedded in the Python loop.
- completion requires fresh non-empty assistant text, configured positive
  completion evidence, absence of configured active/failure evidence, and a
  final stable verification snapshot.
- response-start, activity-stall, and total-response deadlines are distinct;
  zero disables stall/total policies where the schema permits it.
- a submitted turn is never automatically sent again during recovery.
- the Gateway serializes turns within one session; the provider adds no second queue.

Run deterministic coverage with `pytest tests/gpt_auto`. The opt-in live gateway
acceptance is `python tests/gpt_auto/test_session_transport_live.py`.

The `gpt-auto` execution profile disables Gateway session idle/max-lifetime
caps so a durable conversation can remain open for days. It gives a turn 3900
seconds at the Gateway layer, leaving shutdown margin around the provider's
configured 3600-second response policy. Session lifetime and turn lifetime are
separate policies.
