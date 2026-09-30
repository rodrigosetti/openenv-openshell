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

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:1105d646 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex -->
## Beads Issue Tracker

Use Beads (`bd`) for durable task tracking in repositories that include it. Use the `beads` skill at `.agents/skills/beads/SKILL.md` (project install) or `~/.agents/skills/beads/SKILL.md` (global install) for Beads workflow guidance, then use the `bd` CLI for issue operations.

### Quick Reference

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
```

### Rules

- Use `bd` for all task tracking; do not create markdown TODO lists.
- Run `bd prime` when Beads context is missing or stale. Codex 0.129.0+ can load Beads context automatically through native hooks; use `/hooks` to inspect or toggle them.
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.
<!-- END BEADS CODEX SETUP -->
