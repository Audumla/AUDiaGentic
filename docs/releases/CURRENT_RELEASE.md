# Current Release

## Changes

### audit
- [chg_20261020_144909_confirmed-the-deduplication-fi_3460] Confirmed the deduplication fix through exact-head GPT review and a live same-session gateway/CDP test; completion was detected automatically.

### code-fix
- [chg_20261020_122725_prevented-a-gateway-restart-du_8427] Prevented a gateway restart during preflight from repeatedly interrupting a request: only a durable, request-matched proof that browser Send was never dispatched can resume the frozen prompt; all ambiguous cases still fail closed.
- [chg_20261020_125529_gateway-restart-recovery-no-lo_7816] Gateway restart recovery no longer discards proof that a prompt was definitely unsent when opening a replacement provider surface fails; only the matching request owner can advance it to dispatching. Completed GPT review response finalization is also schema-compatible.
- [chg_20261020_131307_prevent-stale-gateway-workers_2671] Prevent stale gateway workers from overwriting or stranding prepared BigCherry requests during restart recovery, and reject project/surface mismatches before submission.
- [chg_20261020_132110_prevent-recovery-checkpoint-co_2473] Prevent recovery checkpoint corruption and ensure a crash during provider-binding registration can be repaired safely without losing the admitted request.
- [chg_20261020_132536_prevent-recovery-code-from-era_8515] Prevent recovery code from erasing the evidence needed to safely resume a BigCherry request before submission or completion is proven.
- [chg_20261020_134101_close-the-remaining-recovery-c_3928] Close the remaining recovery-checkpoint cleanup bypasses identified by GPT by enforcing request ownership for checkpoint writes and durable terminal state for cleanup.
- [chg_20261020_135608_fixed-a-gpt-auto-startup-path_3118] Fixed a GPT-auto startup path where a fresh session could reject its first durable submission checkpoint, and added regression coverage for pre-Send persistence, restart safety, exact project identity, and terminal cleanup.
- [chg_20261020_140206_closed-the-restart-gap-in-gpt_4453] Closed the restart gap in GPT-auto submission recovery: a prepared turn can advance after a restart only after the successor acquires the durable recovery claim.
- [chg_20261020_141539_prevented-watchdog-recovery-fr_9392] Prevented watchdog recovery from completing a queued request with its predecessor’s GPT response. The trace now records when capture is skipped for a foreign turn, and recovery failures remain typed and diagnosable.
- [chg_20261020_143101_prevented-stale-request-metada_2240] Prevented stale request metadata from capturing another turn, added safe rematerialization for completed responses hidden by ChatGPT virtualization, and improved trace evidence for assistant-ID changes and prompt-to-response ordering.
- [chg_20261020_143828_fixed-false-gpt-request-failur_4732] Fixed false GPT request failures caused by ChatGPT mounting the same user message twice in the DOM; distinct later prompts are still recognized as separate turns.
- [chg_20261020_144540_fixed-the-follow-on-completion_3933] Fixed the follow-on completion bug: duplicate DOM copies are collapsed before the gateway derives whether a prompt is unanswered or an assistant response is terminal.
- [chg_20261020_151454_fixed-a-trace-proven-gpt-compl_6379] Fixed a trace-proven GPT completion miss and fresh-session checkpoint rejection without weakening turn identity or no-replay safety. Added bounded diagnostics for future checkpoint mismatches and tracked the separate live-turn handoff gap after manual capture.
- [chg_20261020_160439_prevented-false-submission-pro_6367] Prevented false submission proof and false trace error reports; added tests that keep real transport errors visible and ensure a completed answer does not fabricate prompt-submission identity.
- [chg_20261020_160746_prevented-malformedfuture-rec_8865] Prevented malformed/future reconciliation leases from blocking recovery indefinitely without allowing stale workers or prompt replay.
- [chg_20261020_163204_gateway-traces-now-distinguish_1174] Gateway traces now distinguish how far GPT-auto got through prompt submission without recording prompt content, while preserving the no-duplicate-send rule for ambiguous requests.
- [chg_20261020_163457_a-timeout-writing-the-send-int_2759] A timeout writing the Send-intent checkpoint can no longer be mistaken for a Send click; the gateway records it as pre-click and does not click.
- [chg_20261020_200645_fixed-same-session-gateway-fol_6147] Fixed same-session gateway follow-up failures by safely clearing verified terminal checkpoint residue, preventing provider binding from creating partial checkpoints, and preserving useful owner-fence facts in request traces.
- [chg_20261020_203546_prevent-stale-or-orphaned-gate_1008] Prevent stale or orphaned gateway checkpoints from erasing a successor request by proving terminal turn ownership, preserving ambiguous BigCherry drafts, and improving missing-binding trace diagnostics.
- [chg_20261020_212317_terminal-request-completion-no_4534] Terminal request completion no longer waits for whole-project history compaction, and session expiry follows a consistent lock order to prevent retention/request deadlocks.
- [chg_20261020_215037_repair-lock-contention-and-sam_9252] Repair lock contention and same-session follow-ups, and recover completed responses when conversation URL publication was lost.
- [chg_20261020_221200_prevent-new-prompts-from-faili_6252] Prevent new prompts from failing against stale checkpoints in failed sessions that never acquired a ChatGPT conversation.
- [chg_20261020_221530_keep-the-queued-to-running-own_7175] Keep the queued-to-running ownership handoff intact when retrying session initialization.
- [chg_20261020_222012_fence-failed-session-replaceme_1496] Fence failed session replacement safely and preserve automatic completion across same-conversation follow-ups.
- [chg_20261020_222539_prevent-expired-recovery-attem_5343] Prevent expired recovery attempts or stale captures from publishing a completed request after ownership changes.
- [chg_20261020_223207_verify-that-concurrent-recover_6835] Verify that concurrent recovery-result writers cannot invalidate a capture claim inside terminal commit.
- [chg_20261020_224258_allow-a-manually-captured-pred_1273] Allow a manually captured predecessor's verified checkpoint to release matching idle session memory without clearing another turn.
- [chg_20261020_224444_fence-idle-manual-capture-memo_2965] Fence idle manual-capture memory reconciliation with artifact, checkpoint and conversation identity checks.
- [chg_20261020_224815_attribute-streamed-response-an_7020] Attribute streamed response and thinking activity to the correct current prompt instead of silently discarding it as an older turn.
- [chg_20261020_225345_preserve-exact-captured-turn-r_1601] Preserve exact captured-turn recovery identity across cleanup failures and restarts instead of losing the live-session handoff marker.
- [chg_20261020_225702_provide-an-observation-only-co_5540] Provide an observation-only completion signal for captured GPT turns without stopping provider generation or destroying recovery identity.
- [chg_20261020_231217_let-a-manually-captured-comple_9910] Let a manually captured completed GPT turn release its observer and unblock the same conversation safely, including capture from another process.
- [chg_20261020_231526_keep-the-validated-submission_3098] Keep the validated submission attempt on captured results so the next prompt can reuse the conversation even when request metadata publication lagged.
- [chg_20261020_231950_keep-queued-follow-ups-waiting_4289] Keep queued follow-ups waiting safely when captured-turn memory cleanup is incomplete instead of dispatching them into a stale session.
- [chg_20261020_232113_recognize-long-submitted-promp_9735] Recognize long submitted prompts despite a lost Send acknowledgment or rotating DOM window, without sending them again.
- [chg_20261020_232448_treat-an-already-completed-cap_5026] Treat an already-completed capture race as success when its stored response is valid, rather than showing a misleading dashboard error.
- [chg_20261020_232636_keep-queued-requests-fenced-wh_4578] Keep queued requests fenced when capture acknowledgment loses its CAS, even if local memory cleanup already succeeded.
- [chg_20261020_233802_let-manual-capture-tolerate-no_7046] Let manual capture tolerate normal activity revision updates without weakening turn ownership or checkpoint safety.
- [chg_20261020_234619_preserve-session-checkpoint-id_4033] Preserve session checkpoint identity so captured completed turns do not block follow-up requests.
- [chg_20261020_234817_allow-a-cleared-reusable-gpt-c_5300] Allow a cleared reusable GPT conversation to accept its next request instead of rejecting informational recovery state.
- [chg_20261020_235123_silently-reopen-a-retained-gpt_7262] Silently reopen a retained GPT conversation when its prior automatic-resume generation has failed safely.
- [chg_20261020_235540_reattach-retained-conversation_2526] Reattach retained conversation handles after restart and reject ambiguous failed-session reuse safely.
- [chg_20261020_235747_fully-clear-captured-turn-subm_9097] Fully clear captured-turn submission checkpoints so subsequent requests can reuse the conversation.
- [chg_20261020_235821_allow-safe-cleanup-of-complete_2206] Allow safe cleanup of completed-turn residue on failed local sessions before reopening the retained chat.
- [chg_20261021_000046_prevent-a-newly-prepared-reque_1522] Prevent a newly prepared request from inheriting an older turn's submission attempt.
- [chg_20261021_003217_preserve-submission-order-for_6356] Preserve submission order for queued requests in the same session without blocking unrelated conversations.
- [chg_20261021_004210_avoid-failing-an-unsent-reques_1326] Avoid failing an unsent request when its draft reached ChatGPT but the insertion acknowledgement was lost.
- [chg_20261021_004411_prevent-cancelled-queued-work_4818] Prevent cancelled queued work bypassing session ordering.
- [chg_20261021_004917_reuse-an-already-exact-unsent_2300] Reuse an already exact unsent draft rather than repeatedly typing it.
- [chg_20261021_005623_correctly-distinguish-proven-u_7344] Correctly distinguish proven-unsent composer timeouts from uncertain provider submissions.
- [chg_20261021_005740_automatically-recover-verified_2156] Automatically recover verified pre-Send composer timeouts in the same conversation instead of immediately failing.
- [chg_20261021_010439_allow-verified-unsent-retries_3086] Allow verified-unsent retries to start a fresh attempt in the same conversation without checkpoint-stage conflicts.
- [chg_20261021_010720_do-not-attach-an-earlier-answe_9502] Do not attach an earlier answer as partial output of an unsent request.
- [chg_20261021_011025_preserve-pre-send-recovery-cla_8041] Preserve pre-Send recovery classification in stored request errors.
- [chg_20261021_011520_recognize-completed-code-heavy_6937] Recognize completed code-heavy requests when ChatGPT stores the fence language as a hidden semantic attribute.
- [chg_20261021_012024_recover-completed-responses-ev_8756] Recover completed responses even when ChatGPT keeps visible message counts constant.
- [chg_20261021_013241_avoid-unnecessary-locked-sessi_3999] Avoid unnecessary locked session scans for request histories already protected by saved runtime data.
- [chg_20261021_013436_reduce-retention-lock-pressure_3351] Reduce retention lock pressure while preserving all existing protected histories.
- [chg_20261021_014434_do-not-mistake-error-messages_9210] Do not mistake error messages quoted in an unsent prompt for real ChatGPT failures.
- [chg_20261021_015822_persist-exhausted-recovery-dia_7918] Persist exhausted-recovery diagnostics without attempting an invalid submission-stage transition.
- [chg_20261021_021918_prevent-genuine-conversation-l_7735] Prevent genuine conversation-load recovery from failing on an unrelated submission-stage checkpoint while preserving bounded retry protection.
- [chg_20261021_024201_keep-observing-an-active-gpt-r_3845] Keep observing an active GPT request when renderer message IDs change instead of incorrectly failing it.
- [chg_20261023_010115_prevent-completed-multi-node-g_6563] Prevent completed multi-node GPT replies from remaining stuck on an obsolete assistant node ID.
- [chg_20261023_012034_recover-completed-thinking-plu_3081] Recover completed thinking-plus-answer turns silently while rejecting ambiguous or still-changing replies.
- [chg_20261023_012704_align-manual-response-recovery_6591] Align manual response recovery with automatic completion for proven thinking-plus-final remounts.

### docs
- [chg_20261021_025647_document-reviewed-and-live-tes_6553] Document reviewed and live-tested gateway recovery fixes and retained conversation continuity after restart.
- [chg_20261021_031332_reconcile-stale-gateway-review_6272] Reconcile stale gateway review records with deployed fixes and preserve explicit deferred hardening.
- [chg_20261023_015214_document-reviewed-and-live-val_7181] Document reviewed and live-validated completion recovery and startup trace changes, with remaining latency investigation explicit.

### feature
- [chg_20261023_011002_expose-where-request-startup-s_2596] Expose where request startup spends time without treating preparation diagnostics as GPT progress.

### refactor
- [chg_20261023_013112_remove-competing-completion-re_8747] Remove competing completion recovery paths and keep one shared terminal replacement policy.
