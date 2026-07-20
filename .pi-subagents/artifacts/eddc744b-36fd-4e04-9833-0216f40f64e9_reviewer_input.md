# Task for reviewer

Launch parallel adversarial reviewers for an assessment of the recent multi-file changes introducing a provider-neutral session transport contract (AS28) and session surface resolution (AS29). The work includes foundation neutral transport contracts, ACP adapter wrapper, provider descriptor loader with session surfaces, public execution and transport preparation, and test updates. Use fresh context and have reviewers inspect the repository, relevant instructions, and current diff directly from files and commands. Do not rely on the main conversation history.

Provide 3 distinct reviewer angles:
1. Correctness and regressions - Check whether the change satisfies the request, preserves existing behavior, handles edge cases, and avoids hidden runtime failures
2. Tests and validation - Check whether tests or validation were added at the right layer, whether assertions are meaningful, and whether the chosen verification commands are enough  
3. Simplicity and maintainability - Check for unnecessary complexity, duplicate structure, single-use wrappers, brittle abstractions, confusing names, verbosity, and cleanup that is clearly worth doing

Each reviewer should return concise, evidence-backed findings with file/line references and suggested fixes. Reviewers must not edit files unless explicitly asked for a writer pass.

## Acceptance Contract
Acceptance level: attested
Completion is not accepted from prose alone. End with a structured acceptance report.

Criteria:
- criterion-1: Return concrete findings with file paths and severity when applicable

Required evidence: review-findings, residual-risks

Finish with a fenced JSON block tagged `acceptance-report` in this shape:
Use empty arrays when no items apply; array fields contain strings unless object entries are shown.
`criteriaSatisfied[].status` must be exactly one of: satisfied, not-satisfied, not-applicable.
`commandsRun[].result` must be exactly one of: passed, failed, not-run.
`manualNotes` and `notes` are optional strings; an empty string means no note and does not satisfy `manual-notes` evidence.
```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "specific proof"
    }
  ],
  "changedFiles": [
    "src/file.ts"
  ],
  "testsAddedOrUpdated": [
    "test/file.test.ts"
  ],
  "commandsRun": [
    {
      "command": "command",
      "result": "passed",
      "summary": "short result"
    }
  ],
  "validationOutput": [
    "validation output or concise summary"
  ],
  "residualRisks": [
    "none"
  ],
  "noStagedFiles": true,
  "diffSummary": "short description of the diff",
  "reviewFindings": [
    "blocker: file.ts:12 - issue found, or no blockers"
  ],
  "manualNotes": "anything else the parent should know"
}
```