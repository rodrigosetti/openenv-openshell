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

## Publication boundary

This change prepares the manual for GitHub Pages. Enabling Pages, adding the
publishing workflow, and verifying the live URL belong to the dependent deployment
issue `openenv-openshell-ikw`. Hosted documentation is additional work, not a new
M3 release requirement.
