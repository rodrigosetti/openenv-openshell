# Preparing and pinning environment images

An OpenEnv environment image runs unchanged under OpenShell only if it meets the
runtime's requirements. This guide covers what to check and how to make runs
reproducible.

## Use immutable references

Pass an image reference that cannot change underneath you:

```text
ghcr.io/org/my-env@sha256:02ea3505...      # registry manifest digest (preferred)
sha256:21f3855d...                         # local image ID (local VM lane only)
ghcr.io/org/my-env:latest                  # mutable: avoid for training runs
```

Tags such as `latest` can move between runs, so the code, dependencies, and even
the server port behind them can change. The provider records the reference you
pass in `provider.metadata.image`; it does not resolve tags to digests. Pin the
digest to make that record meaningful, and store it with your results alongside
`policy_digest` and the version fields.

To find a registry digest for a tag:

```bash
docker buildx imagetools inspect ghcr.io/org/my-env:1.2.0 --format '{{.Manifest.Digest}}'
```

For a locally built image on the native VM lane, use the image ID:

```bash
docker image inspect --format '{{.Id}}' my-env:dev
```

A local image ID is a configuration identity on one machine, not a pullable
digest, and rebuilds can produce a new ID. Inspect the ID after each build and
rerun your checks before relying on it. Inspect a digest before adopting it:
the [EchoEnv investigation](echo-env-image.md#rejected-registry-candidate-history)
found a published `latest` image whose architecture, port, and action model did
not match its documentation.

Use digest-pinned base images and lockfiles in your own Dockerfiles, as
[the EchoEnv recipe](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/images/echo/Dockerfile) does, so a
rebuild produces the same software.

## Make the image runnable under OpenShell

Check each item against the gateway's compute driver:

- **Architecture.** The native Apple Silicon VM lane needs `linux/arm64`; the
  Docker driver on x86 hosts needs `linux/amd64`. Many Hugging Face Space images
  are amd64-only.
- **Explicit command.** OpenShell 0.1.2 ignores `ENTRYPOINT`, `CMD`, `WORKDIR`,
  and `ENV`. Read them with `docker image inspect` and supply the equivalent
  `command` and `env_vars`; see [command](configuration.md#command).
- **Executables on the default `PATH`.** The VM runtime may not apply the
  image's `PATH`. Use absolute paths, or link the server launcher into
  `/usr/local/bin` (the EchoEnv image links `uvicorn`).
- **VM networking tools.** The VM driver needs `iproute2` in the image; EchoEnv
  also installs `nftables`.
- **Non-root identity for the Docker driver.** It rejects UID 0 and requires the
  identity to enter and write the workdir. Add a user (for example UID 1000
  `sandbox`) and set `USER`, as
  [`Dockerfile.docker-driver`](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/images/echo/Dockerfile.docker-driver)
  does.
- **Policy access.** The policy must grant read access to the server's code and
  virtual environment (for example `/app`) and write access to what it writes.
  The strict example policies also expect a `sandbox` user and writable
  `/workspace`. See the [policy examples](https://github.com/rodrigosetti/openenv-openshell/blob/main/examples/policies/README.md).
- **Port and health.** The server must listen on `0.0.0.0` at `service_port` and
  answer `GET /health` with 200; OpenEnv clients also need `/ws`.

## Validated images

| Image | Lane | Notes |
| --- | --- | --- |
| [EchoEnv](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/images/echo/Dockerfile), local ID in [`local-image-id.txt`](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/images/echo/local-image-id.txt) | Local 0.1.2 VM, arm64 | Quickstart and E2E tests |
| EchoEnv Docker-driver variant, digest in [`remote-image-ref.txt`](https://github.com/rodrigosetti/openenv-openshell/blob/main/tests/integration/images/echo/remote-image-ref.txt) | Remote 0.1.2 Docker driver, amd64 | Clients need a TLS client certificate on mTLS gateways |
| [coding_env](https://github.com/rodrigosetti/openenv-openshell/blob/main/examples/coding-agent/Dockerfile) | Local 0.1.2 VM, arm64 | [Coding-agent demo](coding-agent-demo.md) |

Other images and drivers are unverified. Validate a new image by running the
[quickstart](https://github.com/rodrigosetti/openenv-openshell/blob/main/README.md#quickstart) with its command, port, and policy, and
check `openshell sandbox list` afterwards to confirm cleanup.
