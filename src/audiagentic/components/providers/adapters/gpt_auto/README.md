# gpt-auto adapter

The gateway owns durable AUDiaGentic sessions. One project-scoped
`GptAutoProviderRuntime` owns a shared Brave/CDP connection and an in-process
Python CDP bridge. Each gateway session owns a `PersistentChat`; its page handle
is volatile and its ChatGPT `/c/<id>` binding is durably installed through the
gateway after the first accepted turn.

Runtime policy lives only in `.audiagentic/config/providers/gpt-auto.yaml`.
The contract is strict: unknown or legacy keys fail instead of being aliased.

Important invariants:

- Gateway ID, ChatGPT conversation ID, request ID, and page handle are distinct.
- A durable gateway session is the project/chat URL pair (`/g/<project>/c/<chat>`),
  not one prompt. Each `agent_task_submit` against that session is a separate
  turn with its own request/turn record and optional provider message IDs.
- Continuing a completed conversation uses the same `session_id` with a new
  prompt; it does not call the unresolved-turn recovery path or create a new
  ChatGPT conversation. Resuming a terminal gateway generation reopens the
  same project/chat URL first, proves quiescence, and then accepts the new turn.
- If a prior turn was interrupted, recovery first matches its provider message
  ID when available, then falls back to one unique bounded prompt-text match.
  Missing IDs are evidence gaps, not automatic failures; ambiguous matches
  remain `RECOVERING` with diagnostics and a resubmit suggestion, and never
  trigger an automatic duplicate send.
- page handles and browser process facts are never durable session identity.
- one browser/CDP bridge serves many chats; closing one chat does not stop either.
- provider tabs are retained when sessions close or the shared runtime stops by
  default, so durable ChatGPT conversations remain resumable; set
  `browser.close-tabs-on-session-close: true` to opt into destructive tab cleanup.
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
