# Release Notes

## v0.3.1

### Audits
- Confirmed the deduplication fix through exact-head GPT review and a live same-session gateway/CDP test; completion was detected automatically.

### Documentation
- Document reviewed and live-tested gateway recovery fixes and retained conversation continuity after restart.
- Reconcile stale gateway review records with deployed fixes and preserve explicit deferred hardening.
- Document reviewed and live-validated completion recovery and startup trace changes, with remaining latency investigation explicit.

### Features
- Expose where request startup spends time without treating preparation diagnostics as GPT progress.

### Fixes
- Prevented a gateway restart during preflight from repeatedly interrupting a request: only a durable, request-matched proof that browser Send was never dispatched can resume the frozen prompt; all ambiguous cases still fail closed.
- Gateway restart recovery no longer discards proof that a prompt was definitely unsent when opening a replacement provider surface fails; only the matching request owner can advance it to dispatching. Completed GPT review response finalization is also schema-compatible.
- Prevent stale gateway workers from overwriting or stranding prepared BigCherry requests during restart recovery, and reject project/surface mismatches before submission.
- Prevent recovery checkpoint corruption and ensure a crash during provider-binding registration can be repaired safely without losing the admitted request.
- Prevent recovery code from erasing the evidence needed to safely resume a BigCherry request before submission or completion is proven.
- Close the remaining recovery-checkpoint cleanup bypasses identified by GPT by enforcing request ownership for checkpoint writes and durable terminal state for cleanup.
- Fixed a GPT-auto startup path where a fresh session could reject its first durable submission checkpoint, and added regression coverage for pre-Send persistence, restart safety, exact project identity, and terminal cleanup.
- Closed the restart gap in GPT-auto submission recovery: a prepared turn can advance after a restart only after the successor acquires the durable recovery claim.
- Prevented watchdog recovery from completing a queued request with its predecessor’s GPT response. The trace now records when capture is skipped for a foreign turn, and recovery failures remain typed and diagnosable.
- Prevented stale request metadata from capturing another turn, added safe rematerialization for completed responses hidden by ChatGPT virtualization, and improved trace evidence for assistant-ID changes and prompt-to-response ordering.
- Fixed false GPT request failures caused by ChatGPT mounting the same user message twice in the DOM; distinct later prompts are still recognized as separate turns.
- Fixed the follow-on completion bug: duplicate DOM copies are collapsed before the gateway derives whether a prompt is unanswered or an assistant response is terminal.
- Fixed a trace-proven GPT completion miss and fresh-session checkpoint rejection without weakening turn identity or no-replay safety. Added bounded diagnostics for future checkpoint mismatches and tracked the separate live-turn handoff gap after manual capture.
- Prevented false submission proof and false trace error reports; added tests that keep real transport errors visible and ensure a completed answer does not fabricate prompt-submission identity.
- Prevented malformed/future reconciliation leases from blocking recovery indefinitely without allowing stale workers or prompt replay.
- Gateway traces now distinguish how far GPT-auto got through prompt submission without recording prompt content, while preserving the no-duplicate-send rule for ambiguous requests.
- A timeout writing the Send-intent checkpoint can no longer be mistaken for a Send click; the gateway records it as pre-click and does not click.
- Fixed same-session gateway follow-up failures by safely clearing verified terminal checkpoint residue, preventing provider binding from creating partial checkpoints, and preserving useful owner-fence facts in request traces.
- Prevent stale or orphaned gateway checkpoints from erasing a successor request by proving terminal turn ownership, preserving ambiguous BigCherry drafts, and improving missing-binding trace diagnostics.
- Terminal request completion no longer waits for whole-project history compaction, and session expiry follows a consistent lock order to prevent retention/request deadlocks.
- Repair lock contention and same-session follow-ups, and recover completed responses when conversation URL publication was lost.
- Prevent new prompts from failing against stale checkpoints in failed sessions that never acquired a ChatGPT conversation.
- Keep the queued-to-running ownership handoff intact when retrying session initialization.
- Fence failed session replacement safely and preserve automatic completion across same-conversation follow-ups.
- Prevent expired recovery attempts or stale captures from publishing a completed request after ownership changes.
- Verify that concurrent recovery-result writers cannot invalidate a capture claim inside terminal commit.
- Allow a manually captured predecessor's verified checkpoint to release matching idle session memory without clearing another turn.
- Fence idle manual-capture memory reconciliation with artifact, checkpoint and conversation identity checks.
- Attribute streamed response and thinking activity to the correct current prompt instead of silently discarding it as an older turn.
- Preserve exact captured-turn recovery identity across cleanup failures and restarts instead of losing the live-session handoff marker.
- Provide an observation-only completion signal for captured GPT turns without stopping provider generation or destroying recovery identity.
- Let a manually captured completed GPT turn release its observer and unblock the same conversation safely, including capture from another process.
- Keep the validated submission attempt on captured results so the next prompt can reuse the conversation even when request metadata publication lagged.
- Keep queued follow-ups waiting safely when captured-turn memory cleanup is incomplete instead of dispatching them into a stale session.
- Recognize long submitted prompts despite a lost Send acknowledgment or rotating DOM window, without sending them again.
- Treat an already-completed capture race as success when its stored response is valid, rather than showing a misleading dashboard error.
- Keep queued requests fenced when capture acknowledgment loses its CAS, even if local memory cleanup already succeeded.
- Let manual capture tolerate normal activity revision updates without weakening turn ownership or checkpoint safety.
- Preserve session checkpoint identity so captured completed turns do not block follow-up requests.
- Allow a cleared reusable GPT conversation to accept its next request instead of rejecting informational recovery state.
- Silently reopen a retained GPT conversation when its prior automatic-resume generation has failed safely.
- Reattach retained conversation handles after restart and reject ambiguous failed-session reuse safely.
- Fully clear captured-turn submission checkpoints so subsequent requests can reuse the conversation.
- Allow safe cleanup of completed-turn residue on failed local sessions before reopening the retained chat.
- Prevent a newly prepared request from inheriting an older turn's submission attempt.
- Preserve submission order for queued requests in the same session without blocking unrelated conversations.
- Avoid failing an unsent request when its draft reached ChatGPT but the insertion acknowledgement was lost.
- Prevent cancelled queued work bypassing session ordering.
- Reuse an already exact unsent draft rather than repeatedly typing it.
- Correctly distinguish proven-unsent composer timeouts from uncertain provider submissions.
- Automatically recover verified pre-Send composer timeouts in the same conversation instead of immediately failing.
- Allow verified-unsent retries to start a fresh attempt in the same conversation without checkpoint-stage conflicts.
- Do not attach an earlier answer as partial output of an unsent request.
- Preserve pre-Send recovery classification in stored request errors.
- Recognize completed code-heavy requests when ChatGPT stores the fence language as a hidden semantic attribute.
- Recover completed responses even when ChatGPT keeps visible message counts constant.
- Avoid unnecessary locked session scans for request histories already protected by saved runtime data.
- Reduce retention lock pressure while preserving all existing protected histories.
- Do not mistake error messages quoted in an unsent prompt for real ChatGPT failures.
- Persist exhausted-recovery diagnostics without attempting an invalid submission-stage transition.
- Prevent genuine conversation-load recovery from failing on an unrelated submission-stage checkpoint while preserving bounded retry protection.
- Keep observing an active GPT request when renderer message IDs change instead of incorrectly failing it.
- Prevent completed multi-node GPT replies from remaining stuck on an obsolete assistant node ID.
- Recover completed thinking-plus-answer turns silently while rejecting ambiguous or still-changing replies.
- Align manual response recovery with automatic completion for proven thinking-plus-final remounts.

### Improvements
- Remove competing completion recovery paths and keep one shared terminal replacement policy.
