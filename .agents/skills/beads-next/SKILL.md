---
name: beads-next
description: Complete one ready Beads issue, validate it, commit its changes, and merge into local main. Use only when explicitly invoked.
---

# Next Beads issue

Explicit invocation of `$beads-next` authorizes committing the selected issue's
completed changes and merging them into local `main`, without another permission
question. This authorization applies only to this invocation and does not include
pushing, publishing, or Dolt remote sync. Follow explicit user overrides and actual
execution permissions.

## Select and implement

1. Read repository `AGENTS.md` and `SPEC.md`; use the repository's Beads skill.
   Run `bd prime` and `bd ready`. Inspect git status and worktrees before editing.
2. Choose the highest-priority ready, unclaimed issue whose dependencies are
   complete. Break ties by roadmap order, then issue ID. Inspect it with
   `bd show <id>` and claim it with `bd update <id> --claim`. Do not take work
   already active in another worktree. If no eligible issue exists, do nothing:
   stop without changing files, creating or updating issues, creating branches,
   committing, or merging. Do not invent replacement work. A brief "No ready
   Beads issue; no action taken" response is sufficient.
3. Work on a `codex/<issue-id>` branch based on local `main`. Use an isolated
   checkout when needed to preserve existing changes or other active work.
   Complete exactly one selected issue; record discovered follow-up scope and
   dependencies in Beads. `SPEC.md` governs disagreements; correct the issue.
4. Implement the acceptance criteria with relevant tests and documentation.
   Run `make check` and applicable integration tests when runtime behavior
   changes. Do not weaken quality or security settings to pass checks.

## Complete and merge

5. Review the final diff for scope and unintended changes. Close the issue only
   after its acceptance criteria and applicable checks pass. Update Beads through
   `bd`, never by editing `.beads/issues.jsonl` directly. Include the relevant
   passive export update if tracked, preserving unrelated ledger history.
6. Stage only changes belonging to this issue and commit with the issue ID in
   the message. Do not sweep unrelated modifications into the commit.
7. Inspect local `main` and its worktree again. If it advanced, merge it into the
   issue branch, resolve conflicts within understood scope, and rerun applicable
   checks on the combined result. Merge the validated issue branch into local
   `main`, preferably with `git merge --ff-only`. Use its existing worktree if
   `main` is already checked out. Preserve unrelated changes; do not force-update
   branches, rewrite history, or discard files to make the merge succeed.
8. Confirm the issue commit is reachable from `main` and inspect final git status.
   Report the issue, validation, commit hash, and local merge result. Do not push.

If implementation cannot finish, record the concrete blocker in Beads, or return
paused/abandoned work to `open` when no concrete blocker exists. If implementation
is complete but commit or merge is blocked, preserve the validated work and report
the exact remaining operation and reason; distinguish implementation completion
from merge completion. Never claim a merge succeeded without verifying it.
