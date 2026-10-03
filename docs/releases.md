# Release preparation and publishing

I10 prepares the `0.1.0` package; I13 prepares publishing; I14 owns the first
usable production release. Setting the version is not publication or a PyPI name reservation.
Production remains blocked until Beads M3 and I13 are closed with evidence.
See the [prepared v0.1.0 release notes](release-notes/0.1.0.md) for scope and limitations.

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
uv run python -m scripts.check_distribution --tag v0.1.0 --index pypi
uv run twine check --strict dist/*
```

The validator requires exactly one wheel and one sdist, matching name/version,
index-compatible dependencies, package typing, README and license. The workflow
installs each artifact into a fresh environment outside the checkout, first
without the SDK and then with the exact prerequisite. Sdist installation rebuilds
the wheel independently. The upload job downloads those validated artifacts;
it does not rebuild them or execute repository source with OIDC privileges.

The wheel intentionally contains only the typed runtime package and distribution
metadata/license. The sdist also ships the SDK prerequisite file, lockfile,
Makefile, SPEC, documentation (including release notes), examples, scripts, and
tests. Beads and agent-local configuration are explicitly excluded. Review the
archive member lists as well as passing the automated validator.

To repeat a clean installation locally, run this for each absolute wheel/sdist
path, from an empty directory outside the checkout:

```bash
uv venv venv --python 3.11
uv pip install --python venv/bin/python /absolute/path/to/distribution
venv/bin/python -c 'from importlib.metadata import version; from openenv_openshell import OpenShellProvider; assert version("openenv-openshell") == "0.1.0"; OpenShellProvider().stop_container()'
uv pip install --python venv/bin/python -r /absolute/path/to/requirements-openshell.txt
venv/bin/python -c 'from importlib.metadata import version; from openenv_openshell._sdk import SDKAdapter; assert version("openshell") == "0.1.2"'
uv pip check --python venv/bin/python
```

Use a separate environment per artifact so that the wheel cannot conceal an
sdist build or dependency problem. These checks do not contact a gateway.

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

## Verified TestPyPI rehearsal

On September 30, 2026, the owner confirmed both PyPI and TestPyPI Trusted
Publishers were configured with the identities above and authorized this
rehearsal. Both GitHub environments were read back through the API: reviewer
`rodrigosetti`, admin bypass disabled, and custom deployment policies allowing
only `v*` tags. Self-review is allowed for the sole owner. The TestPyPI deployment
was approved through the API under that explicit owner authorization.

[Release run 36805618165](https://github.com/rodrigosetti/openenv-openshell/actions/runs/36805618165)
passed all three jobs: build, Trusted Publishing upload, and install from the
actual index. The source is tag
[`v0.0.0`](https://github.com/rodrigosetti/openenv-openshell/tree/v0.0.0), commit
`8d817611b112665384b456ac9fc8fcb1f9ce92fe`. The
[TestPyPI project](https://test.pypi.org/project/openenv-openshell/0.0.0/)
contains the validated wheel and sdist. This version is a packaging rehearsal;
production publication remains subject to M3 and I14.

The release build passed 433 unit tests, strict Pyright/Ruff, 99.50% coverage,
metadata/content validation, strict Twine 7 checks, and clean installation of
both artifacts outside the checkout. The tagged commit also passed the
[Quality workflow](https://github.com/rodrigosetti/openenv-openshell/actions/runs/36781917282)
on Python 3.11–3.14 and the pinned compatibility pair. The index verification
job installed the actual TestPyPI wheel with ordinary dependencies from PyPI
and the official hash-pinned OpenShell 0.1.2 wheel, then passed `uv pip check`
and provider/SDK imports. No gateway was needed for these packaging checks.

The TestPyPI JSON API reported these SHA-256 values, independently matched to
the artifacts downloaded from the successful CI build:

| File | SHA-256 |
| --- | --- |
| `openenv_openshell-0.0.0-py3-none-any.whl` | `5200dc2c532ee42506756b7714939a5e1c2e0871a4029ed389aba44fdd6bf6fe` |
| `openenv_openshell-0.0.0.tar.gz` | `bb41701825b93faa116cb526704a7ba91f6cf78d3279ea23582a087c2403c417` |

The accepted Requires-Dist entries are `httpx>=0.28,<0.29`, `openenv==0.6.0`,
and `pyyaml>=6.0.3,<7`; no direct SDK URL is embedded in published metadata.
Initial local checks also verified actionable rejection of an absent SDK
before gateway access. Actionlint 1.7.12 accepted the workflow. Twine 7 and
publishing action v1.14.2 support Hatch's metadata 2.5.

Production publisher registration is owner-confirmed; its OIDC upload has not
been exercised because the usable-release gate is still separate. No production
package was uploaded. After bringing this evidence onto the newer local main,
`make check` passed 457 unit tests with 99.52% coverage, strict typing and lint.
Those later changes are not part of the immutable `v0.0.0` rehearsal artifacts.

## I10 package preparation evidence — October 1, 2026

Prepared metadata for `0.1.0`, Alpha classification, and a release-notes project
URL; refreshed the lock without widening dependency support. The
[release notes](release-notes/0.1.0.md) retain the cleanup ownership
release blocker, the process-capacity exclusion, remote mTLS incompatibility,
explicit-startup requirements, and image/driver limits.

After integrating current main's TestPyPI evidence and sandbox-name repair,
on Python 3.11.8, `make check` passed 463 unit tests (27 integration tests
deselected), Ruff format/lint, strict Pyright, and 99.52% coverage. The final
wheel and sdist passed `scripts.check_distribution --tag v0.1.0 --index pypi`
and strict Twine checks. Archive inspection confirmed 14 wheel entries: ten
package files including `py.typed`, plus metadata, WHEEL, license, and RECORD.
The sdist includes the documented source material and excludes the Beads and
agent configuration directories.

Each artifact installed independently into a fresh `/tmp` environment, with
dependencies resolved from package metadata rather than the development lock.
The sdist rebuilt its wheel under build isolation. Both installations imported
the public provider from their own `site-packages`, reported version `0.1.0`,
contained `py.typed`, and accepted stop-before-start. Without the SDK, the lazy
adapter raised the actionable installation error before gateway access. After
installing the hash-pinned SDK, the private adapter imported and reported SDK
`0.1.2`; `uv pip check` passed before and after SDK installation.

This is local package evidence only. No tag, upload, production acceptance, or
new runtime compatibility result is asserted. M3, I13, and I14 remain separate
release gates.

## 9zt release-branch reconciliation evidence — October 3, 2026

Merged saved `origin/main` (7cb5c39) into local `main` (2fcf11d) as commit
`8d878a1` on `codex/openenv-openshell-9zt`. The tree contains the SEC8a ownership
safeguards, the S5b remote-OIDC validation, the ZF3 generated-name fix, I10
packaging, and the user manual. The only textual conflict was `README.md`.
Source code at this revision is exactly the merge result; this evidence entry
is documentation only.

With `uv sync --locked --all-groups`, `make check` passed 468 unit tests (29
integration tests deselected), Ruff, strict Pyright, and 99.54% coverage. Against
the local OpenShell 0.1.2 gateway (`vm` driver, Docker running for image
resolution) and the pinned native arm64 EchoEnv image, 15 integration tests
passed in 198.83 seconds: collision and replacement ownership, provider startup
and failure cleanup, the quickstart with its default-generated name, unmodified
OpenEnv clients, policy-before-execution, and managed credentials. No sandboxes
remained afterwards. SEC8c (atomic deletion) remains a separate release blocker;
this branch-local result is not M3 acceptance evidence.
