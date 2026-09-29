# Roadmap

This is the working task board for [`SPEC.md`](SPEC.md). Each item should fit in
one focused development session and leave the repository passing `make check`.

Status: `✅` done · `⬜` open · `🚧` active · `⛔` blocked. Change the icon and
add a short note or PR/commit link when status changes. Dependencies are task
IDs; tasks whose dependencies are done may run in parallel.

## Current state

- ✅ **F1 — Package foundation:** `src/` layout, Hatchling build, typed package,
  supported Python versions, Apache-2.0 license, and locked dependencies.
- ✅ **F2 — Quality foundation:** Ruff, strict Pyright, pytest, branch coverage
  with a 95% floor, unit/integration lanes, and `make check`.
- ✅ **F3 — API skeleton:** Public provider/config/resource/error imports,
  OpenEnv `ContainerProvider` inheritance, state and metadata models, and
  explicit not-implemented lifecycle methods.

## Ready to work in parallel

Tasks with complete dependencies:

- **P5** HTTP readiness

## Milestone 0 — Runtime spike

- ✅ **S1 — Map the current OpenShell SDK.** Exact lifecycle signatures,
  response fields, private model boundaries, service-exposure contract, and the
  0.1.2 target versus 0.0.116 lock incompatibility are recorded in
  [`docs/openshell-sdk-contract.md`](docs/openshell-sdk-contract.md).
  _Depends: F1._
- ⛔ **S1a — Select the SDK distribution and workload-model boundary.** Blocked
  on choosing the official 0.1.2 wheel source and either a stable public
  workload/policy builder, an explicitly tested generated-model dependency, or
  a narrow CLI adapter. _Depends: S1._
- ✅ **S2 — Document a repeatable local test setup.** Verified CLI/gateway
  0.0.116, default workspace, native macOS VM compute, routed HTTP, and sandbox
  deletion; [setup and evidence](docs/local-openshell-testing.md). `make check`
  passes. Revalidate when S1a selects the target distribution. _Depends: F1._
- ✅ **S3 — Select and pin the EchoEnv test image.** Native arm64 recipe,
  immutable local image ID, upstream CMD, port 8000, and MCP action contract
  are recorded in [image findings](docs/echo-env-image.md). The opt-in
  [image probe](tests/integration/test_echo_image.py) passes VM provisioning,
  routed `/health` and `/ws`, and deletion on 0.0.116; `make check` passes.
  Revalidate after S1a selects the runtime pair. _Depends: S2._
- ⬜ **S4 — Build the one-file lifecycle spike.** Create a sandbox from the
  image, declare its service, wait for OpenShell readiness, obtain the routed
  URL, and always delete it. Keep this separate from production code.
  _Depends: S1a, S2, S3._
- ⬜ **S5 — Prove protocol connectivity.** Through the routed URL, verify HTTP
  `/health`, WebSocket `/ws`, `reset`, `step("hello")`, and `state`; record local
  and remote gateway findings. _Depends: S4._
- ⬜ **S6 — Resolve spike questions.** Decide target-port precedence, service
  naming, image constraints, service authentication, WebSocket keepalive, and
  whether policy must exist before workload start. Update `SPEC.md` where the
  spike supplies an answer. _Depends: S5._

**Gate M0:** EchoEnv completes `reset` and `step` through an OpenShell-managed
service and the sandbox is deleted afterward.

## Milestone 1 — Provider lifecycle

- ✅ **P1 — Validate configuration and naming.** Implement constructor keyword
  arguments, positive ports/timeouts/resources, safe names, generated
  `openenv-<image>-<suffix>` names, defensive copies, and non-secret label
  validation. _Depends: F3._
- ⬜ **P2 — Define the private SDK adapter.** Isolate unstable OpenShell imports
  and models behind a small typed protocol; translate connection failures and
  make dependency/version errors actionable. _Depends: S1a._
- ⬜ **P3 — Translate create requests.** Map image, environment variables,
  workspace, service exposure, labels, providers, resources, gateway, and
  optional configuration into the adapter without logging secrets.
  _Depends: P1, P2, S6._
- ⬜ **P4 — Implement `start_container`.** Enforce one live sandbox, create it,
  wait for OpenShell readiness, extract and validate the service URL, populate
  state, and return the base URL. _Depends: P3._
- ⬜ **P5 — Implement HTTP readiness.** Poll `<base_url>/health` using monotonic
  deadlines, bounded request timeouts, configurable intervals, and a typed
  timeout error. _Depends: P1._
- ⬜ **P6 — Implement cleanup.** Make `stop_container` idempotent; support
  `keep_sandbox`; delete and wait with the expected sandbox ID; clear ownership
  correctly after absence, partial initialization, failure, and timeout.
  _Depends: P2, P4._
- ⬜ **P7 — Guarantee failed-start cleanup.** Cover create, readiness, missing
  URL, and state-update failures with best-effort deletion while preserving the
  primary error and safely reporting cleanup failure. _Depends: P4, P6._
- ⬜ **P8 — Add lifecycle logging and metadata.** Emit the specified logging
  events and expose non-secret run metadata including image, service URL,
  workspace, timestamps, versions, IDs, and later the policy digest.
  _Depends: P4, P6._
- ⬜ **P9 — Close/context behavior.** Ensure `close()` and context-manager exit
  release provider-held resources and cannot leak an owned sandbox.
  _Depends: P6._
- ⬜ **P10 — Public API integration check.** Exercise
  `from_docker_image(..., provider=OpenShellProvider())` without modifying
  OpenEnv and document the supported OpenEnv range. _Depends: P5, P7, S5._

## Unit-test lane

- ✅ **T1 — Build a typed fake adapter.** Deterministic lifecycle results,
  per-operation failures, and mutation-safe call capture are covered by
  `tests/unit/test_fakes.py`. _Depends: F3._
- ⬜ **T2 — Test successful lifecycle and request mapping.** Cover defaults,
  overrides, environment variables, workspace, names, labels, providers,
  resources, ports, returned URL, state, metadata, and call order.
  _Depends: P3, P4, T1._
- ⬜ **T3 — Test startup and readiness failures.** Cover create failure,
  OpenShell timeout, missing/malformed service URL, HTTP errors/statuses, and
  OpenEnv timeout. _Depends: P5, P7, T1._
- ⬜ **T4 — Test every cleanup path.** Cover before start, duplicate stop,
  already absent, keep mode, partial state, delete failure, and deletion wait
  timeout. _Depends: P6, P7, T1._
- ⬜ **T5 — Test secret-safe errors and logs.** Assert credentials, tokens, and
  raw secret environment values never appear in messages or captured logs.
  _Depends: P7, P8, T1._
- ⬜ **T6 — Add contract fixtures.** Assert the private adapter uses the exact
  supported SDK method names, keyword arguments, and response fields so SDK
  churn fails clearly. _Depends: P2, S1._

**Gate M1:** The provider works with an existing OpenEnv client, lifecycle unit
coverage exceeds 90%, all failure paths clean up, and `make check` passes.

## Milestone 2 — Policy and security

- ⬜ **SEC1 — Load explicit policies.** Accept a YAML path or mapping, reject
  missing/malformed/unsupported policy input, normalize deterministically, and
  never fall back to permissive behavior. _Depends: P1, S6._
- ⬜ **SEC2 — Compute policy provenance.** Generate a stable SHA-256 digest from
  normalized policy content and add it to run metadata. _Depends: SEC1, P8._
- ⬜ **SEC3 — Author strict and image-mode examples.** Validate their exact
  schema against the supported OpenShell release and explain compatibility vs.
  least privilege. _Depends: S1, SEC1._
- ⬜ **SEC4 — Apply policy before execution.** Pass explicit policy through the
  adapter at the correct lifecycle point and prove invalid policy prevents the
  workload from starting. _Depends: P3, SEC1, S6._
- ⬜ **SEC5 — Filesystem security test.** Prove denied host/SSH reads and allowed
  workspace/temp writes while the OpenEnv session remains usable.
  _Depends: SEC3, SEC4, P10._
- ⬜ **SEC6 — Network security tests.** Prove deny-by-default egress, explicitly
  allowed destinations, and continued control-plane/WebSocket operation.
  _Depends: SEC3, SEC4, P10._
- ⬜ **SEC7 — Credential guidance and provider mapping.** Document that secrets
  should use OpenShell providers, test provider selection mapping, and verify
  managed credential material is not trivially printable. _Depends: P3, SEC4._
- ⬜ **SEC8 — Security review.** Check non-root behavior, resource limits,
  command-injection boundaries, labels, ingress, egress, exception redaction,
  and cleanup blast radius against the spec. Resolve the observed
  [VM Landlock/PID-limit gaps](docs/echo-env-image.md) before claiming enforcement.
  _Depends: SEC5, SEC6, SEC7._

**Gate M2:** Explicit policies are fail-closed and digestible; denied filesystem
and network operations are demonstrated without breaking the OpenEnv session.

## Milestone 3 — Upstream-quality integration

- ⬜ **I1 — Build the reusable E2E fixture.** Start or connect to a local
  gateway, select a workspace/image, capture diagnostics, and guarantee cleanup
  on test interruption. _Depends: S5, P7._
- ⬜ **I2 — Add EchoEnv E2E.** Verify health, WebSocket, repeated reset/step,
  state, close, and post-close sandbox deletion. _Depends: I1, P10._
- ⬜ **I3 — Add security E2E jobs.** Run the filesystem and network denial tests
  separately from pure unit tests. _Depends: I1, SEC5, SEC6._
- ⬜ **I4 — Add CI quality jobs.** Run formatting, linting, strict typing, unit
  tests, coverage, lock validation, and package builds across supported Python
  versions. _Depends: M1 gate._
- ⬜ **I5 — Add gated integration CI.** Run real OpenShell tests only on capable
  runners with clear skip reasons, bounded timeouts, and cleanup diagnostics.
  _Depends: I2, I3, I4._
- ⬜ **I6 — Test compatibility ranges.** Exercise the oldest and newest
  supported OpenEnv/OpenShell pairs, align SDK and gateway release families,
  and narrow dependency bounds when behavior differs. _Depends: I2, T6._
- ⬜ **I7 — Write architecture and security docs.** Explain lifecycle, routing,
  control-plane vs. egress traffic, policy precedence, credentials, metadata,
  failure modes, remote gateway constraints, and non-goals. _Depends: S6, SEC8._
- ⬜ **I8 — Build the canonical coding-agent demo.** Show successful OpenEnv
  execution plus allowed workspace access and denied filesystem/network access,
  with deletion visible at the end. _Depends: I2, I3._
- ⬜ **I9 — Finish user documentation.** Add a copy/paste install and quickstart,
  configuration reference, troubleshooting, immutable-image advice, and the
  single polished demo path. _Depends: I6, I7, I8._
- ⬜ **I10 — Prepare the v0.1 package.** Set release metadata/version, inspect
  wheel and sdist contents, test installation in a clean environment, and write
  release notes with known limitations. _Depends: I4, I6, I9._
- ⬜ **I11 — Coordinate upstream.** Open focused OpenEnv and OpenShell design
  discussions backed by the working EchoEnv demo; incorporate feedback without
  expanding the initial provider contract. _Depends: I8._

**Gate M3 / v0.1:** Every acceptance criterion in §39 of `SPEC.md` is checked,
CI and E2E are green, the quickstart is reproducible, and no sandbox leaks in
success or failure tests.

## Milestone 4 — Trusted verification

- ⬜ **V1 — Write the threat model and interface proposal.** Define trusted
  verifier invariants, approved artifact boundaries, result authenticity,
  cleanup, and whether this stays provider-local or needs an upstream concept.
  _Depends: I11._
- ⬜ **V2 — Prototype safe artifact transfer.** Copy only explicitly selected
  outputs from the agent sandbox into a clean verifier sandbox; reject path
  traversal, links, device files, and unbounded artifacts. _Depends: V1, P2._
- ⬜ **V3 — Implement verifier lifecycle.** Start a clean pinned image under a
  separate policy, run a trusted command, collect bounded results, and always
  delete the verifier sandbox. _Depends: V2, P7._
- ⬜ **V4 — Add adversarial tests.** Attempt verifier replacement, startup
  tampering, artifact escape, result spoofing, network leakage, and cleanup
  failure. _Depends: V3._
- ⬜ **V5 — Document and demo trusted verification.** Show agent sandbox A,
  approved artifacts, verifier sandbox B, and reproducible reward collection;
  link the implementation back to the upstream discussion. _Depends: V4._

**Gate M4:** Agent-controlled state cannot alter verifier startup, execution,
or result collection in the documented threat model.

## Milestone 5 — Reproducible Open Agent Run

- ⬜ **R1 — Define the run-record schema.** Include model/environment revisions,
  requested and resolved image identity, OpenEnv/OpenShell/provider versions,
  policy digest, trajectory, audit references, verification result, and reward;
  explicitly exclude secrets and private task contents. _Depends: P8, V1._
- ⬜ **R2 — Capture immutable runtime provenance.** Record image digests and
  component versions where the APIs expose them; warn clearly when only mutable
  tags are available. _Depends: I6, R1._
- ⬜ **R3 — Export bounded audit data.** Select useful OpenShell enforcement
  events, redact sensitive values, associate them with the run, and document
  retention/availability limitations. _Depends: SEC8, R1._
- ⬜ **R4 — Publish one reproducible artifact.** Produce a Hugging Face
  dataset/artifact containing the schema, trajectory, audit data, verification
  result, and reward with replay instructions. _Depends: R2, R3, V5._
- ⬜ **R5 — Independently reproduce the run.** Replay from pinned inputs, compare
  outputs and security metadata, document expected nondeterminism, and close any
  missing-provenance gaps. _Depends: R4._

**Gate M5:** A third party can inspect and replay a published run from pinned
inputs with its policy, sandbox provenance, verification result, and reward.

## Deferred extensions

- ⬜ **D1 — Policy generator proposal.** Map OpenEnv manifests, declared tools,
  external APIs, and artifact paths to reviewable YAML without claiming least
  privilege. _Depends: SEC8, I11._
- ⬜ **D2 — Policy generator implementation and tests.** Produce deterministic,
  schema-valid proposals and require explicit user review before use.
  _Depends: D1._
- ⬜ **D3 — `doctor` CLI decision.** Reassess whether gateway, workspace,
  service, WebSocket, and version diagnostics justify a dedicated CLI after
  real-world support experience. _Depends: I10._

## Release checklist

Use this compact checklist at the M3 gate; evidence should point to tests or
documentation rather than merely changing the box.

- ⬜ Existing OpenEnv clients need no source changes.
- ⬜ The environment runs inside OpenShell and is reachable only through its
  managed service route.
- ⬜ `/health`, `/ws`, `reset`, `step`, and `state` all work.
- ⬜ Normal close and every tested startup failure delete owned sandboxes.
- ⬜ `stop_container()` is idempotent and `keep_sandbox` is explicit.
- ⬜ Explicit policies are supported and never silently broadened.
- ⬜ Network and filesystem denials are demonstrated.
- ⬜ Unit tests require no OpenShell installation; real E2E tests are separate.
- ⬜ The README quickstart and canonical demo work from a clean environment.
- ⬜ Package, compatibility, typing, lint, test, and coverage checks pass.
