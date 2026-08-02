# Creating Plans

A guide for agents creating, implementing, and managing plan items in `docs/planning/`.

---

## 1. When to create a plan

- User asks to create a plan or work items for a task
- Tracking multi-step implementation across sessions
- Reviewing or updating the state of outstanding items

---

## 2. Creating a plan item

**Before creating, check for an existing item covering the same work**: run
`plan_list_items(state='active')` and scan titles/plans for overlap — including
*other* plans, since one root cause (a standards change, a review finding) often
spawns items in parallel sessions. If an item already covers it, update that item
(via a review, per section 8) instead of creating a duplicate. Two half-specified
duplicates are worse than either alone: implementers pick one at random and the
deltas in the other are silently lost.

Use `plan_create_item` to add a new item. Required fields: `plan` (directory name), `title`.
The `id` is auto-generated — **do not supply it**.

Plan-item and review IDs are globally unique across every plan and lifecycle
state. Never create or copy a planning Markdown file by hand. If the
ag-planning MCP is unavailable, record the proposed work in the Notes of an
existing related item and defer creation; do not guess or reserve an ID.

```yaml
plan_create_item:
  plan: code-cleanup
  title: Refactor error handling to use AudiaGenticError
   priority: P1
   work: M
   description: ...
  steps: ...
```

---

## 3. Referencing standards

Use `plan_list_standards` to discover available architecture and design standards.
Pick the ones relevant to your task based on their descriptions.

**How to reference standards in a plan:**

1. Call `plan_list_standards` to see available standards with their descriptions
2. Identify which standards apply to your task
3. Include a `Standards` section in your plan item listing the relevant standards:

```markdown
## Standards

- <standard-id> — <brief note on which rules apply>
```

*Which* standards you list is a judgment call — include the ones that are actually
relevant, don't check boxes. But for any item that touches `src/`, the Standards section
itself is required (see section 7): either name the applicable standards or state
`none apply` deliberately. Items shipped with empty Standards sections have previously
correlated directly with standards violations in the implementation (raw `ValueError`
at public boundaries, `print()` in library code, cross-component imports failing
boundary tests). The goal is that the implementing agent finds the rules that matter
*before* writing code, and the Definition of Done (section 5) has something concrete
to verify against.

---

## 4. Item lifecycle

1. Create items with `plan_create_item` — lands in `docs/planning/active/<plan>/`
2. Revise content with `plan_update_item` as work progresses
3. Close handled reviews with `plan_set_review_state(review_id, 'closed')`
4. Mark done with `plan_set_state(item_id, 'completed')` only when the Definition of Done
   in section 5 is satisfied — every step done, every validation criterion executed, suite green
5. Transition superseded or outdated items to `superseded` or `deprecated` with `plan_set_state`; remove stale items with `plan_delete_item`

Do not mark a parent item completed just because its reviews were incorporated.
Keep unfinished work pending or in a terminal discard state. Do not leave handled reviews in `created` or `considered`.

---

## 5. Implementing a plan item

Rules for the agent doing the implementation. These are **mandatory**, not guidance —
violations here have previously shipped items marked completed that were 0–20%
implemented, a red test suite, and code contradicting the repo's own boundary tests.

### Before starting

1. Read the item in full, including Notes — corrections and scope changes live there.
2. Call `plan_list_reviews(review_of=<item_id>)` and read every open review (`created`
   or `considered`). Open reviews are unresolved findings against the item: **address
   each one in the implementation or dispute it in writing via `plan_update_review`**.
   Never implement past an open review as if it didn't exist.
3. Read the standards listed in the item's Standards section (and
   `docs/standards/ARCHITECTURE_STANDARDS.md` for any item touching `src/`).
4. Verify the item's factual claims (line numbers, call-site counts, API signatures)
   still hold. If the code has drifted, update the item first via `plan_update_item`.

### While implementing

- Follow the Steps as written. If a step turns out to be wrong, impossible, or you have
  a better design: **stop and record the deviation** — update the item (or add a review)
  describing what changed and why, *before* writing code that diverges. Silent
  redesigns are not acceptable, even good ones.
- If the item is blocked on another item that hasn't actually landed (not just marked
  completed — actually landed and working), leave it `pending` with a blocked note in
  Notes. Never fake the dependency's existence or stub around it.
- If scope must shrink, split the item: complete what genuinely shipped as a
  re-scoped item, and create a new pending item for the remainder. Never mark the
  original completed with the remainder silently dropped.
- Never write comments, docstrings, or docs claiming work is done that isn't
  ("migrated onto X" when nothing calls X). Aspirational documentation is a defect.

### Definition of Done — required before `plan_set_state(item_id, 'completed')`

Check every box; if any fails, the item stays `pending`:

1. **Every step** in Steps is implemented, or its deviation is recorded on the item.
2. **Every criterion** in Validation is *executed literally* — if it says "grep confirms
   zero references", run the grep; if it says "regenerate via tool X", run tool X; if it
   says "subprocess-level test", write it. A validation criterion you didn't run is a
   failed criterion.
3. **The full unit test suite is green** (`python -m pytest tests/unit`), not just the
   tests you added. Architecture-boundary tests are part of the suite; a red boundary
   test is an architecture violation, not a test problem. When the item **moves, renames,
   or deletes a module**, running the full suite is non-negotiable and a residual-reference
   grep over `src/` alone is not sufficient: the old dotted path also hides in
   **string-literal references** that no import-shaped scan catches — `monkeypatch.setattr("old.path...")`,
   `mock.patch("old.path...")`, `importlib.import_module`, patch decorators, and dotted
   paths in config/YAML. Grep the **whole repo including `tests/`** for the old module
   path as a bare string, and only the green full suite — not the grep — proves the move
   landed. (A grep scoped to `src` with an `import`-shaped pattern is what let a completed
   item ship 5 tests that failed with `ModuleNotFoundError` on the deleted module.)
4. **Standards compliance verified** against the item's Standards section — including
   error handling (no raw `ValueError` at public boundaries), logging (no `print()` in
   library code), and layer boundaries (no new cross-component imports without an
   explicit, documented decision).
5. **Open reviews on the item are resolved** — addressed or disputed, then closed via
   `plan_set_review_state`.
6. **Generated artifacts regenerated** where the item requires it (e.g. CLAUDE.md via
   `apply_provider_surfaces`) and the generated output verified to match the source edit.

Complete items **one at a time**, running the Definition of Done per item. Bulk-completing
a batch of items in one pass without per-item verification is how partial and false
completions slip through.

---

## 6. Item ID convention

Combine a short uppercase plan prefix with a sequence number: `CC07`, `LSP01`, `ML01`.
Choose a prefix matching the plan name (`CC` → code-cleanup, `LSP` → lsp-mcp-enhancement).

When declaring dependencies, prefer a YAML list of item IDs so validation and
sequencing tools can read it without interpreting prose:

```yaml
blocked-by:
  - CC07
  - LSP01
```

---

## 7. Plan sections

Each plan item supports these sections:

- **Description** — What needs to be done and why
- **Steps** — How to do it (ordered list)
- **Files** — Which files are affected. List the files the implementer *edits*; if a
  generated artifact is also affected, mark it as generated output, not an edit target
- **Validation** — How to verify the work is correct. Write criteria as **executable
  checks** (a command, a grep, a named test) with an observable pass/fail — "works
  correctly" is not a criterion. The implementer is required to run each one literally
- **Effort & Risk** — Complexity assessment and risks
- **Standards** — Relevant architecture/design standards. **Required for any item whose
  Files touch `src/`**; write `none apply` explicitly if that is the considered answer
- **Notes** — Anything else (assumptions, alternatives considered, deviations recorded
  during implementation)

### Level of detail

The bar: **an agent with no context beyond the item and the referenced standards can
implement it without inventing design decisions.** Concretely:

- **Anchor claims to the code.** Name files, functions, and line numbers for every call
  site the item asserts exists ("loader.py:180-238, ~23 call sites found via grep"), and
  verify them at write time — a plan built on stale line numbers sends the implementer
  to the wrong code. Scale this with complexity: a `simple` doc tweak needs a path;
  a `complex` refactor needs the full call-site inventory.
- **Resolve design decisions in the plan, or mark them blocking.** Any point where the
  implementer could plausibly choose between two designs (a directory layout, an event
  name, a collision policy, an API shape) must either be decided in the item — with the
  chosen option stated concretely — or be explicitly labelled `BLOCKING decision` so it
  is resolved by review *before* implementation starts. An unstated decision is not
  flexibility; it is a defect that will be resolved arbitrarily mid-implementation.
- **State interim and failure behavior**, not just the end state: what happens on the
  degraded path (component absent, no live session, headless run), and what the system
  does in the window between this item landing and its dependents landing.
- **Name cross-item dependencies both ways.** If this item builds on another, say which
  one and what it consumes from it; if it changes another item's premise, update that
  item in the same pass.
- **Verify external API claims** (SDK signatures, tool behavior) by inspection before
  writing steps against them — "confirmed via `inspect.signature`, 2026-07-05" belongs
  in the item.

A step an implementer must research before they can start it is a step the plan
hasn't finished writing.

---

## 8. Reviews

Reviews are linked to plan items for quality gates. Use `plan_create_review` to create one.
Reviews have a lifecycle: `created` → `considered` → `closed`.
The parent item may be pending in `active/` or completed in `completed/`.
Use reviews on completed or already-implemented items when you need to capture
post-implementation findings, audits, regressions, or code review feedback
without reopening history or cloning the original item.

An open review (`created`/`considered`) on a pending item is a **gate**: the implementer
must address or dispute it before the item can be completed (see section 5). Reviewers
should write findings so they are actionable — name the file, the defect, and the
concrete fix or decision required.

---

## 9. Quick reference

| Tool | Purpose |
| --- | --- |
| `plan_create_item` | Create a new plan item |
| `plan_list_standards` | List available architecture/design standards |
| `plan_list_groups` | List all plans with item counts |
| `plan_list_items` | List items (filter by state or plan) |
| `plan_get_item` | Read a plan item by ID |
| `plan_update_item` | Update fields or sections of an existing item |
| `plan_set_state` | Transition state: `completed` moves to completed/ |
| `plan_delete_item` | Permanently remove a plan item |
| `plan_create_review` | Create a review linked to a plan item |
| `plan_list_reviews` | List reviews (filter by state, plan, or parent) |
| `plan_get_review` | Read a review by ID |
| `plan_set_review_state` | Transition review state: `closed` moves to completed/ |
| `plan_update_review` | Update fields or sections of an existing review |
| `plan_delete_review` | Permanently remove a review |
