# Beads in linked worktrees

The live Dolt database is the execution ledger. Linked Git worktrees on this
machine resolve `bd` to the primary checkout's `.beads` directory and share its
issue state and configuration. Run `bd where` in each worktree to verify this;
do not initialize an independent database for each source branch.

`.beads/issues.jsonl` is a generated snapshot, not a source file. It is ignored
and removed from the Git index. The repository explicitly sets:

```yaml
export.auto: false
export.git-add: false
import.auto: false
```

These settings prevent issue operations and pre-commit hooks from exporting or
staging snapshots, and prevent checkout/merge hooks from importing stale JSONL
into the shared ledger. Keep the Beads hooks installed for their other duties.
Never use `git add -f` on the export or resolve its conflicts by importing it.

## Adopting the change on older branches

Once the cleanup is committed on main, bring that commit into active branches
before further integration. An older branch that modified the tracked snapshot
may encounter a modify/delete conflict during this one-time migration. Preserve
any snapshot needed for an audit outside the repository, then resolve that path
by keeping its deletion:

```bash
git rm -- .beads/issues.jsonl
```

That resolves only the generated file; resolve code conflicts separately.
The Dolt database remains intact. Do not restore the snapshot from the older
branch or import it to reconstruct issue status. Inspect `bd show` and issue
history when reconciling actual task outcomes.

Before committing, verify:

```bash
git ls-files -- .beads/issues.jsonl  # must print nothing
git check-ignore .beads/issues.jsonl
bd config show --source config.yaml
bd where
```

## Exports and database synchronization

An optional local snapshot can still be produced explicitly:

```bash
bd export -o .beads/issues.jsonl
```

The ignored file is for viewing or interchange. It does not contain the full
database history and does not back up the database.

Local linked worktrees already share the database; no issue-data merge or remote
sync is needed between them. Cross-machine synchronization and backup are
separate from source Git operations. Inspect `bd dolt remote list` and configure
an appropriate Dolt remote before using `bd dolt push` or `bd dolt pull`. Use
`bd backup --help` for full database backup options. This cleanup does not
configure a remote or publish database contents; commit/push/sync still follow
the authorization rules in `AGENTS.md`.

See the upstream [sync concepts](https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md)
for the distinction between the Dolt ledger and JSONL exports.
