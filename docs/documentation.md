# Contributing to the manual

The manual uses the repository Markdown as its source. Existing guides in
`docs/` are rendered directly; the getting-started page includes the README's
Requirements, Install, Quickstart, and Known limitations sections through a
small MkDocs hook. Keep the README quickstart equal to `examples/quickstart.py`;
the existing offline unit test verifies that relationship.

## Install and preview

From a clean checkout with Python 3.11+ and uv:

```bash
uv sync --locked --only-group docs
make docs-serve
```

Open <http://127.0.0.1:8000/openenv-openshell/>. MkDocs mounts the preview at the
project subpath configured by `site_url`, matching the intended GitHub Pages
layout. Check navigation, Search, and the guide you changed at that path.
OpenShell, Docker, and a gateway are unnecessary for building or previewing.

## Validate a change

```bash
make docs-build
uv lock --check
```

The strict build treats missing navigation pages, missing link targets, and
missing internal anchors as errors. Generated `site/` output is ignored. The
Quality workflow installs only the locked docs group in its documentation job
and runs the same strict build for pull requests.

For a full contributor environment and the repository checks:

```bash
uv sync --locked --all-groups
make check
```

Add user guides to the relevant navigation section in `mkdocs.yml`. Put test
evidence and maintainer procedures in Engineering reference. Keep pre-alpha
status, pinned versions, and security limitations explicit; a passing docs build
provides no new runtime compatibility evidence.

## Links and assets

Link to other manual pages with relative Markdown paths, such as
`configuration.md#command`. Use relative paths for assets under `docs/`; avoid
root-relative URLs, which lose the `/openenv-openshell/` project prefix.
Files outside `docs/`, including scripts, policies, and tests, use full GitHub
source links under `https://github.com/rodrigosetti/openenv-openshell/blob/main/`.
Directory links use `tree/main/`. The strict build validates local targets and
anchors; it does not fetch external links.

See the official [MkDocs configuration guide](https://www.mkdocs.org/user-guide/configuration/)
for link validation and project-subpath preview behavior.

## GitHub Pages setup

The publication URL is <https://rodrigosetti.github.io/openenv-openshell/>.
The [User manual workflow](https://github.com/rodrigosetti/openenv-openshell/blob/main/.github/workflows/pages.yml)
builds the locked docs group, uploads `site/` with the official Pages artifact
action, and deploys it through the official Pages deployment action. Every action
is pinned to a full commit SHA. The build has only `contents: read`; only the
deployment job has `pages: write` and `id-token: write`. Checkout does not retain
credentials, and deployment uses the `github-pages` environment with concurrency
that lets an in-flight deployment finish.

After explicit authority to commit, push, and publish the reviewed changes,
a repository administrator must enable Pages:

1. Open repository **Settings → Pages** and select **GitHub Actions** as the
   build and deployment source. Do not select a branch publishing source.
2. In **Settings → Environments → github-pages**, restrict deployment branches
   to `main`. Retain any required reviewers; approve the deployment when prompted.
3. Merge the reviewed workflow and documentation changes into `main`. The push
   starts publication. Pages must be enabled before that deployment runs.

The equivalent Pages source API setup, using an administrator's authenticated
GitHub CLI, is:

```bash
# Create the Pages configuration when none exists.
gh api --method POST repos/rodrigosetti/openenv-openshell/pages -f build_type=workflow
# For an existing site, change its source instead.
gh api --method PUT repos/rodrigosetti/openenv-openshell/pages -f build_type=workflow
gh api repos/rodrigosetti/openenv-openshell/pages --jq '{build_type,html_url}'
```

Run the appropriate create or update command, not both. The workflow reads this
configuration with automatic enablement disabled; it does not receive an admin
token or modify repository settings. See GitHub's
[custom Pages workflow requirements](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## Publication and recovery

The site tracks `main`, including unreleased documentation; it is not a
release-version archive. A push to `main` or an explicit manual dispatch on
`main` builds and deploys the checked-out revision. Dispatch on any other ref
skips publication. Pull requests run the Quality workflow's strict docs build
without Pages permissions or deployment. Forks cannot publish to the canonical
site. Hosted documentation is additional work, not a new M3 release requirement.

To redeploy the current `main` after correcting setup or a transient failure:

```bash
gh workflow run pages.yml --ref main
gh run list --workflow pages.yml --branch main --limit 5
gh run view RUN_ID --json headSha,event,conclusion,url
gh run watch RUN_ID --exit-status
```

Use the numeric run ID from the list. Inspect failed logs with
`gh run view RUN_ID --log-failed`. For a build failure, reproduce `make docs-build`
locally and fix the source on `main`. For deployment failures, confirm the Pages
source is `workflow`, the environment allows `main`, required approvals are
satisfied, and Actions may run the pinned official actions. A failed build cannot
deploy; check the last successful deployment before assuming the site changed.
To restore older content, revert the offending source change through review on
`main` and deploy that revision. Re-running an older successful workflow can
publish stale content; dispatch on current `main` for routine recovery.

## Verify publication

Local build success is not live-site evidence. After the deployment succeeds:

1. Record the workflow run URL, its `headSha`, and the successful deployment in
   `openenv-openshell-ikw`.
2. Fetch the landing page over HTTPS without a GitHub login, cookies, or tokens:
   `curl --fail --location https://rodrigosetti.github.io/openenv-openshell/`.
3. In an anonymous browser, follow navigation to getting started, configuration,
   security, and troubleshooting. Search for `service_port` and `policy`, open
   result links, and verify styles and scripts load under `/openenv-openshell/`.
4. Follow repository and example source links and verify the README manual link
   and package `Documentation` URL resolve to the working site. The README guide
   table and package `Source documentation` URL retain access to source guides.

Close the deployment issue only after recording this evidence. If publication
authority or administrator access is missing, record that concrete blocker.
