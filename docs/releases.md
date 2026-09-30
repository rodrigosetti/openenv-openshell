# Release preparation and publishing

I13 prepares publishing; I14 owns the first usable production release. Version
`0.0.0` is development metadata, not a public release or a PyPI name reservation.
Production remains blocked until Beads M3 and I13 are closed with evidence.

## SDK and gateway prerequisites

[Package indexes reject direct URL dependencies](https://setuptools.pypa.io/en/stable/userguide/dependency_management.html#direct-url-dependencies).
The published wheel/sdist therefore has no OpenShell Requires-Dist entry.
This is a packaging decision, not a change to supported runtime versions:
only the official SDK/gateway **0.1.2** contract is supported. The development
group and lock retain the official wheel URL and SHA-256. The private adapter
rejects missing or different SDK versions before gateway access; it never
substitutes the incompatible SDK currently on PyPI.

Install the prerequisite into the same virtual environment as the provider:

```bash
python -m pip install 'openshell @ https://github.com/NVIDIA/OpenShell/releases/download/v0.1.2/openshell-0.1.2-py3-none-any.whl#sha256=8c409da4f176d42418d92366fe201f47cceef2c0fa432bfbce2bf938649d59cf'
```

From a checkout, `uv sync --locked --all-groups` installs the pinned SDK and
release tools. `requirements-openshell.txt` provides the same prerequisite for
artifact validation. Never replace it with an unconstrained `pip install
openshell`. A real run also needs a registered 0.1.2 gateway, compatible workload
image, explicit command and policy: see [local setup](local-openshell-testing.md)
and [startup constraints](image-startup.md). Artifact import checks do not prove
runtime readiness, remote service support, or SPEC.md section 39 acceptance.

## Owner setup

Create GitHub environments `testpypi` and `pypi` for
`rodrigosetti/openenv-openshell`. Require a maintainer reviewer, prevent bypass,
and restrict deployment refs to version tags (`v*`). If preventing self-review,
assign another trusted maintainer; otherwise a sole owner cannot approve their
own dispatch. Verify the effective protections in repository Settings before
running uploads. Do not grant OIDC permission to the build job.

Register separate [Trusted Publishers](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)
on PyPI and TestPyPI. For a new project use each account's pending-publisher
form; for an existing project an owner must add the publisher. Use these exact
identity fields:

| Field | PyPI | TestPyPI |
| --- | --- | --- |
| Project | `openenv-openshell` | `openenv-openshell` |
| Owner | `rodrigosetti` | `rodrigosetti` |
| Repository | `openenv-openshell` | `openenv-openshell` |
| Workflow filename | `release.yml` | `release.yml` |
| Environment | `pypi` | `testpypi` |

Account setup is performed by the account owner. Do not store long-lived index
tokens in repository secrets. A pending publisher does not reserve the name;
TestPyPI ownership does not confer PyPI ownership. The repository must contain
the reviewed workflow on its default branch before dispatching it.

## Local validation

```bash
uv sync --locked --all-groups
make check
# Start from an empty dist/; preserve any artifacts you still need elsewhere.
uv build --no-build-isolation
uv run python -m scripts.check_distribution --tag v0.0.0 --index testpypi
uv run twine check --strict dist/*
```

The validator requires exactly one wheel and one sdist, matching name/version,
index-compatible dependencies, package typing, README and license. The workflow
installs each artifact into a fresh environment outside the checkout, first
without the SDK and then with the exact prerequisite. Sdist installation rebuilds
the wheel independently. The upload job downloads those validated artifacts;
it does not rebuild them or execute repository source with OIDC privileges.

## TestPyPI rehearsal

Choose a unique canonical development version in `pyproject.toml`, refresh
`uv.lock`, validate and commit it on main, and tag exactly `v<version>`. Do not
reuse an uploaded version or overwrite a tag. Push source and tag only when
authorized. Then dispatch manually (example version must match source):

```bash
gh workflow run release.yml --ref v0.0.0 --field index=testpypi
```

The default destination is TestPyPI. No push, pull request or release event
triggers an upload. A branch dispatch skips the build; only tags whose commits
are ancestors of main are eligible. Approve the protected `testpypi` job after
reviewing its source commit and build results. The `verify-index` job installs
the actual indexed wheel without dependencies from TestPyPI, then installs
ordinary dependencies from PyPI and the SDK from its hash-pinned official URL.
It avoids mixing package indexes via `--extra-index-url`.

Record the workflow run URL, tag/commit, indexed artifact hashes, installation
result and publisher/environment configuration evidence in I13. If index
propagation is delayed, rerun only verification after the files are visible.
Do not mark TestPyPI acceptance from local Twine checks alone.

## Production eligibility and I14

Before production, verify every M3 checklist item against SPEC.md section 39,
with green CI/E2E and an independently reproduced quickstart. Close M3 only
with that evidence; also close I13 after the real rehearsal and both publisher
configurations are verified. Check project-name availability at execution time.
Do not upload a placeholder to reserve it.

For the reviewed stable version (at least `0.1.0`), set repository variables
`APPROVED_RELEASE_TAG` to the exact `v<version>`, `APPROVED_RELEASE_COMMIT` to
the full tagged commit SHA, and `M3_EVIDENCE_URL` to the
reviewable M3 acceptance record. These variables express the maintainer's
approval; the workflow cannot query the local Beads database or prove the
linked evidence. Require the `pypi` environment reviewer to check both closed
issues and that evidence against the tagged source before approval. Revoke the
approved tag variable after publication. Protect tags against modification.

```bash
gh workflow run release.yml --ref v0.1.0 --field index=pypi
```

The production gate rejects mismatched approval, missing evidence, placeholders,
prereleases and development versions. I14 must additionally verify the installed
release's real reset/step/state/cleanup path, record its PyPI URL, immutable
source tag and release notes, and document remaining limitations.

## Recovery

On build or metadata failure, fix the source and rerun checks; no index files
have been uploaded. On OIDC failure, check exact owner/repository/workflow and
environment claims on the correct index; do not fall back to an API token.
On upload failure, inspect the index before retrying: one file may have arrived.
Do not enable skip-existing to conceal an artifact mismatch. Index versions
cannot be overwritten; use a new version/tag after a partial or faulty release.
Yank a bad production release when appropriate and publish a corrected version.
Record the incident and validation evidence in Beads.

## Evidence for this preparation

On September 30, 2026, the GitHub `pypi` and `testpypi` environments were
created and read back through the API: reviewer `rodrigosetti`, admin bypass
disabled, and custom deployment policies allowing only `v*` tags. Self-review
is allowed so the sole owner can approve a manual dispatch. PyPI/TestPyPI
publisher registrations and upload remain unverified.

Local `make check` passed on Python 3.11.8: 425 unit tests, strict Pyright and
Ruff, 99.50% branch coverage. Wheel and sdist metadata/content checks and strict
Twine 7 checks passed. Each artifact installed outside the checkout into a fresh
virtual environment; imports and missing-SDK rejection passed before installing
the prerequisite, then exact SDK adapter imports and `uv pip check` passed.
Actionlint 1.7.12 accepted the release workflow. Twine 7 and the publishing action
v1.14.2 support Hatch's metadata 2.5; the older Twine 6 validator rejected it.
No gateway/runtime behavior was changed or newly certified by these checks.

Local results and unresolved owner actions are recorded in I13. Until its
TestPyPI run and both publisher configurations are linked, the issue remains
incomplete and I14 remains blocked. This document does not claim external setup
or upload has occurred.
