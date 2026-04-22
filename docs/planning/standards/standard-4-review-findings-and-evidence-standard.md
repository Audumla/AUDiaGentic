---
id: standard-4
label: Review findings and evidence standard
state: ready
summary: Default standard for how reviews should present findings, evidence, severity,
  and residual risks.
---







# Standard

Default standard for how reviews in AUDiaGentic-based projects should present findings, evidence, assumptions, and residual risks.

# Source Basis

This standard is derived from repository review doctrine and general engineering review best practices, adapted for planning-led and code-review work in this repository.

Sources:

- Repository review doctrine in `AGENTS.md`
- [Google Engineering Practices — Code Review](https://google.github.io/eng-practices/review/)
- [OWASP Code Review Guide](https://owasp.org/www-project-code-review-guide/)
- Project planning and documentation conventions

# Requirements

1. Reviews must lead with findings when findings exist. Summaries and overviews come after the concrete issues.
2. Findings must be prioritized by severity and user or system impact.
3. Each finding must include evidence that lets a reader verify the claim quickly:

   - file reference or planning item reference
   - behavior, risk, or regression being described
   - why it matters

4. Reviews must distinguish between:

   - confirmed defects or risks
   - open questions
   - assumptions made during review
   - residual gaps such as missing tests or incomplete verification

5. If no findings are present, the review must say so explicitly and call out any remaining uncertainty.
6. Review output must not quietly expand into implementation work unless the normalized workflow or task explicitly allows that scope.
7. Planning reviews should also call out missing standards, missing links, invalid references, or misleading status where relevant.
8. Architectural reviews must evaluate compliance with standard-0011 (component architecture): layering violations, missing extension points, config hardcoded in logic, and undeclared module contracts.
9. Security-relevant findings must be called out separately and include impact and recommended remediation, not just observation.

# Default Rules

- Prefer concise, evidence-backed findings over long narrative summaries.
- Use stable file or planning-item references whenever possible.
- Keep severity language understandable and consistent: use critical, high, medium, low.
- Record missing verification as a risk, not as an afterthought.
- Do not conflate style preferences with defects; call out style issues separately if at all.

# Suggested Finding Structure

- severity
- location or affected item
- issue summary
- impact or risk
- evidence
- recommended follow-up

# Non-Goals

- Enforcing one exact review template for every provider.
- Replacing project-specific audit or compliance workflows.
- Requiring implementation proposals in every review.
