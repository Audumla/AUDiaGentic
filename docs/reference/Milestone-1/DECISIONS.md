# Decisions and Full Original-Plan Reconciliation

## Replacement decision

This pack is self-contained. Delete the old active `agent-sessions` folder and replace it with this pack. Git history is the only archive required.

No useful original feature was intentionally discarded. Original work was either:

- rewritten under the same ID;
- absorbed into a broader canonical plan;
- carried forward under a new ID after `AS46`;
- dropped only when it was a superseded implementation slice, duplicate authority, or historical review artifact.

## Original plan disposition

| Original | Disposition in this pack |
|---|---|
| AS08 | carried forward as **AS47** |
| AS09 | carried forward as **AS48** |
| AS10 | carried forward as **AS49** |
| AS13 | carried forward as **AS50** |
| AS14 | carried forward as **AS51** |
| AS17 | carried forward as **AS52**, limited to remaining supervision work |
| AS19 | replaced and expanded by **AS19** |
| AS21 | replaced and expanded by **AS21** |
| AS26 | carried forward as **AS53** |
| AS27 | carried forward as **AS54** |
| AS28 | absorbed into **AS19**; no separate neutral-transport plan remains |
| AS29 | replaced and expanded by **AS29** |
| AS30 | replaced and expanded by **AS30** |
| AS31 | replaced and corrected by **AS31** |
| AS32 | carried forward as **AS55** |
| AS37 | absorbed into **AS21** layered status projection |
| AS38 | carried forward as **AS56** with the public integration decision included |
| AS39 | absorbed into **AS19** as the already-landed transport-observation slice/baseline |
| AS40 | replaced and expanded by **AS40** |
| AS41 | original surface-selection responsibility absorbed into **AS29/AS40**; new **AS41** owns Pi lifecycle/state/output/cancel baseline |
| AS42 | carried forward as **AS57** |
| AS43 | carried forward as **AS58** |
| AS44 | generic capability declaration absorbed into **AS29**; execution/exposure split across **AS44** and **AS58** |

## Old review files

Old `reviews/AS*/RV*.md`, preservation matrices, pack-validation reports, reference maps, and sequence/review documents are not copied forward. Their surviving requirements are incorporated into plan steps, validation, architecture rules, or the disposition table above.

## Settled decisions

- Pi RPC and Pi ACP remain independent selectable surfaces.
- Exactly one surface owns a session generation; there is no automatic fallback or dual ownership.
- Generic capabilities may originate with one provider when semantics are clear and unsupported behavior is explicit.
- Hooks/plugins/process observations are evidence sources, not execution or lifecycle authorities.
- Evidence precedence and confidence replace voting and heuristics.
- Lifecycle, terminal outcome, user content, diagnostics, and provider telemetry remain separate lanes.
- Durable binding identity and public status never expose raw provider refs.
- Windows and Linux capability evidence are independent; Linux Docker does not prove Windows and vice versa.
- Active planning contains current executable truth; Git contains planning history.
