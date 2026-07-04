# Creating Plans

A guide for agents creating and managing plan items in `docs/planning/`.

---

## 1. When to create a plan

- User asks to create a plan or work items for a task
- Tracking multi-step implementation across sessions
- Reviewing or updating the state of outstanding items

---

## 2. Creating a plan item

Use `plan_create_item` to add a new item. Required fields: `plan` (directory name), `title`.
The `id` is auto-generated — **do not supply it**.

```
plan_create_item:
  plan: code-cleanup
  title: Refactor error handling to use AudiaGenticError
  priority: P1
  complexity: mid
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

This is **guidance, not dogma** — include standards that are actually relevant. Don't list
standards just to check boxes. The goal is to make sure the agent implementing the plan
can quickly find the rules that matter.

---

## 4. Item lifecycle

1. Create items with `plan_create_item` — lands in `docs/planning/active/<plan>/`
2. Revise content with `plan_update_item` as work progresses
3. Close handled reviews with `plan_set_review_state(review_id, 'closed')`
4. Mark done with `plan_set_state(item_id, 'completed')` only when implementation and validation are done
5. Remove stale, superseded, or cancelled items with `plan_delete_item`

Do not mark a parent item completed just because its reviews were incorporated.
Keep unfinished work pending. Do not leave handled reviews in `created` or `considered`.

---

## 5. Item ID convention

Combine a short uppercase plan prefix with a sequence number: `CC07`, `LSP01`, `ML01`.
Choose a prefix matching the plan name (`CC` → code-cleanup, `LSP` → lsp-mcp-enhancement).

---

## 6. Plan sections

Each plan item supports these sections:

- **Description** — What needs to be done and why
- **Steps** — How to do it (ordered list)
- **Files** — Which files are affected
- **Validation** — How to verify the work is correct
- **Effort & Risk** — Complexity assessment and risks
- **Standards** — Relevant architecture/design standards (optional)
- **Notes** — Anything else (assumptions, alternatives considered)

---

## 7. Reviews

Reviews are linked to plan items for quality gates. Use `plan_create_review` to create one.
Reviews have a lifecycle: `created` → `considered` → `closed`.
The parent item may be pending in `active/` or completed in `completed/`.
Use reviews on completed or already-implemented items when you need to capture
post-implementation findings, audits, regressions, or code review feedback
without reopening history or cloning the original item.

---

## 8. Quick reference

| Tool | Purpose |
|---|---|
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
