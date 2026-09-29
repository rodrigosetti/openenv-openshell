# Repository instructions

## Sources of truth

- Read `SPEC.md` before changing behavior or public APIs. It defines the product
  requirements, security posture, milestones, and acceptance criteria.
- Read `TODO.md` before starting roadmap work. It is the live execution ledger;
  do not maintain a competing task list elsewhere.
- If `SPEC.md` and `TODO.md` disagree, follow `SPEC.md` and correct `TODO.md` in
  the same change.

## Keeping `TODO.md` current

Every change that advances, blocks, splits, adds, or invalidates roadmap work
must update `TODO.md` in the same branch or pull request.

- Select task IDs whose dependencies are complete before implementing them.
- Change a selected task from `⬜` to `🚧` while it is actively owned. Avoid
  claiming unrelated tasks or tasks already active in another worktree.
- Change `🚧` to `✅` only after its stated outcome is implemented, relevant
  tests and documentation are present, and the applicable checks pass.
- Use `⛔` only for a concrete blocker. Add a brief note naming the missing
  decision, dependency, permission, or external capability needed to unblock it.
- Return abandoned or paused work to `⬜` unless a concrete blocker remains.
- When work uncovers more than one session of additional scope, add new,
  narrowly scoped task IDs with explicit dependencies instead of silently
  expanding the current task.
- Keep dependencies accurate when tasks are added, removed, reordered, or
  split. A task may appear in “Ready to work in parallel” only when every listed
  dependency is complete.
- Update milestone gates and the release checklist only when there is test or
  documentation evidence. Do not infer completion from partial implementation.
- Preserve completed entries as history. If a completed behavior regresses,
  add a repair task or reopen the original task with a short explanation.
- Keep the board concise: link to implementation details in code, tests, or
  `SPEC.md` rather than duplicating them in `TODO.md`.

For changes unrelated to the roadmap, update `TODO.md` only if they alter task
status, dependencies, scope, or readiness.

## Development expectations

- Keep the provider a thin adapter over public OpenEnv and OpenShell APIs.
- Isolate unstable upstream SDK details behind the private compatibility or
  adapter boundary, with typed fakes and contract tests.
- Preserve fail-closed policy behavior, secret-safe logs/errors, idempotent
  cleanup, and cleanup after partial startup failures.
- Unit tests must not require an OpenShell installation or gateway. Mark real
  runtime tests with `integration` and keep them in `tests/integration`.
- Maintain strict typing and linting. Run `make check` before declaring a task
  complete; run the relevant integration tests when runtime behavior changes.
- Do not lower lint, typing, coverage, or security settings merely to make a
  change pass. Use narrow, documented exceptions only when an upstream contract
  requires them.
