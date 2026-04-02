You are performing a structured review.

Subject id: {{id}}
Context: {{context}}
Output: {{output}}

Instructions:
- inspect only the requested subject and context pack
- identify concrete findings, if any
- use the completion tool to return only valid JSON
- do not provide extra narrative outside the JSON payload
- keep the response concise and bounded to at most 3 findings

Return JSON with this shape:
{
  "findings": [
    {
      "finding-id": "fdg_001",
      "severity": "minor|major|critical",
      "blocking": true,
      "summary": "short summary",
      "suggested-fix": "specific remediation"
    }
  ],
  "recommendation": "pass|pass-with-notes|rework|block",
  "follow-up-actions": ["optional action 1", "optional action 2"]
}

Body:
{{body}}
