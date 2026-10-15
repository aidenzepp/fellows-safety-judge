---
name: conventional-commits
description: Use when deciding whether work should be committed, staging changes, or creating Git commits in a repository.
---

# Conventional Commits

Use this skill when preparing commits.

The goal is a commit history that reads like a small design document. Each commit should be targeted, reviewable, and meaningful on its own. A commit does not need to be large; it needs to represent one coherent reason for change.

## Decide Whether To Commit

A natural checkpoint identifies a good time to commit; it does not grant permission to commit.

- When the user asks for commits, or the repository workflow clearly calls for completed implementation work to be committed, commit coherent work at natural checkpoints.
- Treat experiments, spikes, comparisons, testing grounds, and ongoing design work as uncommitted working states. Do not commit merely because one version works.
- Unless commits are already authorized, ask whether the user wants exploratory work committed once it becomes a coherent candidate worth preserving.
- If the request and repository instructions do not make the expectation clear, ask before the first commit. Once the user authorizes commits for the work, do not repeatedly ask at every checkpoint.

## Commit Prefixes

Use these prefixes as the default vocabulary:

- `feat:` for new product behavior, new developer-facing capability, or new reusable API surface
- `fix:` for correctness fixes, regressions, crashes, broken workflows, or user-visible bugs
- `refactor:` for behavior-preserving structure, naming, boundary, or API reshaping
- `chore:` for repository maintenance, dependency updates, generated metadata, tooling, config, or cleanup
- `test:` for test-only changes or reusable test infrastructure
- `docs:` for documentation-only changes
- `style:` for presentation-only UI/CSS changes that do not alter behavior
- `perf:` for measurable performance work
- `build:` for package manager, bundler, compiler, or artifact pipeline changes
- `ci:` for CI workflow changes
- `revert:` for explicit reversions

Prefer the most specific truthful prefix. Avoid vague subjects such as `update`, `cleanup`, `misc`, or `changes`.

Optional scopes are fine when they clarify the boundary (`feat(api):`, `chore(lint):`). Do not invent noisy scopes.

## Plan Commits Before Staging

Before staging, inspect the whole change:

```bash
git status --short
git diff --stat
git diff
```

Write a short commit plan: one sentence for each independently understandable and reversible reason for change. A task, issue, conversation, or branch is not automatically one commit.

During implementation, commit finished and verified slices at natural checkpoints when committing is appropriate. This prevents unrelated changes from accumulating into a single diff that must be untangled later.

Split at story boundaries:

- separate unrelated concerns, even when they touched nearby files
- separate tooling/config/dependency changes from product or library behavior
- separate reusable API additions from their first usage when each is independently meaningful
- separate changes that have different rollback or verification boundaries
- keep tests with the behavior when the tests are the proof for that behavior
- split reusable test infrastructure into its own `test:` commit when it supports later commits
- keep documentation with the change it directly explains; split unrelated documentation cleanup
- keep mechanical formatting separate only when it would obscure the semantic diff
- exclude demos, scratch files, generated churn, and local experiments unless the user explicitly wants them kept

A clean DAG is not the same as many tiny commits. Do not split a change into commits that only make sense after reading future commits unless you are intentionally telling a migration story.

Do not justify a broad commit merely because all changes belong to the same request, touched the same files, or are easier to stage together.

### Boundary Examples

- A feature and the tests that prove it: one `feat:` commit.
- A behavior-preserving refactor followed by a feature: a `refactor:` commit, then a `feat:` commit.
- A lint configuration change and documentation that explains that exact policy: one `chore:` commit can be appropriate.
- A lint configuration change plus unrelated README cleanup: separate `chore:` and `docs:` commits.
- Several experimental configurations under discussion: no automatic commit; ask once the user selects a coherent candidate.

## Stage Carefully

Stage by path or hunk so the index matches the intended story:

```bash
git add path/to/file
git add -p
git diff --cached --stat
git diff --cached
```

Avoid `git add .` unless the working tree has already been inspected and every changed file belongs in the same commit.

## Write The Message

Use an imperative, concise subject:

```text
feat: add settings loader for the runtime environment
chore: remove unused ruff ignore
fix: reject blank text labels
```

Add a body only when the commit needs context that is not obvious from the diff:

- why this boundary exists
- what was deliberately excluded
- what migration or compatibility trade-off was chosen
- what verification proves the change

## Verify The Boundary

Before committing, run the narrowest useful checks for the staged story. Prefer the repo's normal hygiene commands when relevant (format, lint, typecheck, test).

If a check is skipped, say why in the handoff. If a commit is intentionally not green on its own because it is part of a local migration sequence, make that explicit before committing.

## Final Pass

Before reporting completion:

- confirm `git status --short`
- confirm the new log tells the story in order
- report the commit hashes and the checks that ran
- do not push unless the user confirms the remote target
