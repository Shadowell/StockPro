# Sprint 01 Contract: First User Journey

## Goal

Establish the first usable end-to-end path for the product and make it verifiable by script or manual QA.

## In Scope

- Implement one primary user flow.
- Add or document the minimum checks required to verify that flow.
- Update progress and QA handoff files.

## Out of Scope

- Broad redesigns outside the selected user path
- Secondary features
- Premature refactors

## Deliverables

- Working implementation for one user journey
- Updated `scripts/check.sh` or equivalent verification
- QA report for the sprint

## Done Means

- The selected journey can be exercised from start to finish.
- A repeatable verification path exists.
- The next session can see what changed and what remains.

## Verification

```bash
./scripts/check.sh
```

Manual or QA checks:

- Walk through the target user path once.
- Capture the main issues, if any.

## Risks / Notes

- The first sprint should optimize for clarity and verification, not completeness.

## Handoff

- Next likely step: improve the same journey or start the second highest-priority flow.
