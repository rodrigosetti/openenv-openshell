# Public repository baseline

I12 establishes the external repository after the completed M0 lifecycle spike,
following SPEC.md section 42. It does not require waiting for the production
provider or the v0.1 release gate.

## Identity and publication status

Canonical URL: <https://github.com/rodrigosetti/openenv-openshell>.
The public repository was created under `rodrigosetti` on September 30, 2026,
after the user explicitly approved committing and publishing this baseline.
Project metadata uses this URL for source, issues, and README documentation.
The publication branch is `main`; origin uses
`https://github.com/rodrigosetti/openenv-openshell.git`. I12 records verification
of public visibility, origin, and the published commit.

## Baseline review

- README distinguishes implemented configuration, HTTP readiness, offline policy
  loading, and private request translation from unfinished public startup and
  cleanup. It links the local M0 evidence and states image, remote routing,
  startup, security acceptance, and verifier limitations.
- The Apache-2.0 license is retained. Version `0.0.0` and the pre-alpha classifier
  remain development metadata; no PyPI name reservation or production release
  is claimed. Release automation and production uploads belong to I13 and I14.
- Gitleaks 8.30.1 scanned all Git refs and the working tree with redacted output:
  no leaks found. Its release archive was verified against the official release
  checksum. A separate scan of 225 historical blobs found no supported token,
  private-key, credential-URL, or personal home-path patterns.
- Tracked files and historical paths were reviewed. Local databases, credentials,
  dependency environments, caches, build output, and editor state are ignored.
  Shared agent settings and hooks contain portable commands. The checked-in
  EchoEnv Docker configuration ID and loopback routes are deliberate test
  evidence, not public registry artifacts or remote services.
- Existing history and Beads exports contain contributor identity/contact
  metadata. They are retained as project history; the Beads export remains
  passive and is not edited to change live issue data.
- Local Markdown targets and upstream public documentation links were checked.
  Three obsolete NVIDIA documentation URLs were replaced by version-pinned
  OpenShell source documentation. Links to this project's intended GitHub
  repository become usable after publication.

Secret scans detect known patterns and do not prove absence of every possible
secret. No known secret or private runtime artifact was found in this review.

## Validation

On September 30, 2026, a fresh temporary source export with no virtual
environment passed `uv sync --locked --all-groups` and `make check` on Python
3.11.6. The lockfile resolved 135 packages and installed 126. Ruff formatting and
lint passed, strict Pyright reported zero errors/warnings, and all 271 unit
tests passed with 99.40% branch coverage (95% required); nine integration tests
were excluded. Dependencies came from the normal uv cache/network, and no
OpenShell gateway was required. The working checkout passed the same gates.

All 69 local Markdown targets/anchors passed validation. The external link
check returned HTTP 200 for the upstream references after the three repairs;
project URLs are verified as part of publication. `git diff --check` passed.
Runtime behavior is unchanged; this preparation does not rerun or extend the
existing M0 compatibility claims.

## Publication procedure

Commit the reviewed changes on the publication branch, then create the empty
public repository and configure origin:

```bash
gh repo create rodrigosetti/openenv-openshell --public \
  --description "Experimental OpenEnv ContainerProvider adapter for NVIDIA OpenShell"
git remote add origin https://github.com/rodrigosetti/openenv-openshell.git
git push -u origin HEAD:main
```

Publish only the reviewed branch, not every local branch or tag. Verify public
visibility, the default branch, the published commit, and metadata links;
record the canonical URL and commit in I12. Close I12 only after that evidence
is present. CI work (I4) can then proceed; PyPI publication still requires its
own dependencies and usable-release acceptance.
