# Product Spec

## Product Summary

`codex-project-template` is a reusable starting point for building a development harness around Codex. Its job is to help a repository store context, define sprint-sized work, verify outcomes, and preserve handoff information so coding can continue across sessions or machines.

## Users

- Individual developers using Codex in day-to-day project work
- Teams that want a shared harness structure before building plugins or background automation

## Core User Journeys

1. Start a new project with a stable Codex operating structure.
2. Turn a vague feature request into a sprint contract and implement it incrementally.
3. Review a completed sprint with QA notes and preserve the next step for a later session.

## Product Priorities

1. Keep the harness small, readable, and easy to adopt.
2. Make long-running coding tasks resumable through files.
3. Support progressive growth toward stronger QA, skills, and automation.

## Technical Shape

- Frontend: not required by the template
- Backend: not required by the template
- Storage: markdown files and repository history
- Integrations: Codex, optional local skills, optional automation, optional project-specific tooling

## Constraints

- The template should stay useful without requiring heavy infrastructure.
- New structure should be added only after a workflow proves repetitive or fragile.

## Non-Goals

- Replacing project-specific engineering judgment
- Forcing a single stack, framework, or deployment model

## Acceptance Direction

The primary acceptance flow is: define a sprint, implement within that sprint, run verification, record QA, and leave clear progress for the next Codex run.

## Open Questions

- Which additional local skills are worth standardizing after the first few real projects?
- When should the template evolve into a plugin or automation bundle?
