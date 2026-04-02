# Reference: Harness Design for Long-Running Applications

## Source

- Title: `Harness design: Building long-running applications with LLMs`
- URL: <https://www.anthropic.com/engineering/harness-design-long-running-apps>

## Why It Matters To This Repository

This repository aims to become a practical development harness for Codex-driven coding. The Anthropic article is relevant because it describes how long-running software work improves when the harness, not just the model, is designed carefully.

## Key Ideas Captured Here

### 1. Long tasks need structure

The article argues that long-running application development fails when a model is asked to do too much in one pass. This template reflects that by introducing sprint contracts and explicit handoff files.

### 2. Planning, generation, and evaluation should not collapse into one fuzzy step

The article presents a `planner -> generator -> evaluator` style loop. This repository does not hard-code three agents, but it preserves the same separation through:

- `docs/spec.md`
- `docs/contracts/`
- `docs/qa/`

### 3. The sprint contract is the real control point

The article highlights that implementation works better when the builder and evaluator agree on what the current sprint means and how it will be checked. In this repository, the sprint contract is the main unit of execution.

### 4. File handoff matters

The article emphasizes that long-running work should pass through files instead of depending on a single uninterrupted session. That idea directly maps to:

- `docs/progress.md`
- `docs/contracts/`
- `docs/qa/`

### 5. Verification needs its own attention

The article points out that self-evaluation is unreliable. This repository therefore keeps QA as a separate artifact instead of assuming implementation success.

## How This Template Applies The Article

- `AGENTS.md` stores stable project rules.
- `docs/spec.md` stores higher-level intent.
- `docs/contracts/` stores the active sprint boundary.
- `scripts/check.sh` gives one place to start verification.
- `docs/qa/` records evaluator-style findings and verdicts.

## Planned Follow-Through

This reference should guide future iterations of the template, especially:

1. stronger acceptance testing
2. automation-safe sprint contracts
3. richer local skills
4. optional background execution patterns

## Notes

- This file records the source and the applied ideas.
- It intentionally summarizes and adapts the article instead of reproducing the full text.
