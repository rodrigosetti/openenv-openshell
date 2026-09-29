# EchoEnv image investigation (S3)

## Candidate pin

Inspected on 2026-09-29:

```text
registry.hf.space/openenv-echo-env@sha256:5e6068b14b13cf829ccaefe0549e1dea0199f9509f056a3c90f748cf72271348
```

This is the immutable manifest resolved from the upstream `latest` tag, not
an approved image for the local VM lane. Do not substitute `latest` in future
spikes. The registry currently returns a single Linux **amd64** manifest,
not a multi-platform index. The Apple Silicon setup from
[the S2 guide](local-openshell-testing.md) uses the native VM driver.

Image configuration inspection established:

- No configured entrypoint; working directory `/app`.
- CMD: `sh -c 'cd /app/env && uvicorn server.app:app --host 0.0.0.0 --port 8000'`.
- Target port: **8000**, including the image's exposed-port metadata and
  healthcheck. Do not assume the current Space documentation's port 7860
  applies to this digest.
- Python search path `/app/env:/app/src`; executable search path starts with
  `/app/.venv/bin`.
- Healthcheck requests `http://localhost:8000/health`.
- OCI revision label: `2faae32750487168419afb4f1f8dc4a9efaac5c7`.
  This is an inherited label, not proof of the EchoEnv source revision.

## Runtime and protocol evidence

A disposable Docker container with `--platform linux/amd64`, no published host
ports, and the configured uvicorn command (bound to loopback for this probe)
returned HTTP 200 with `{"status":"healthy"}` from `/health`. A
`websockets.sync.client.connect('ws://127.0.0.1:8000/ws')` handshake succeeded.
Importing `server.app:app` also showed `/health` as an HTTP route and `/ws` as
an `APIWebSocketRoute`. These checks establish image-level endpoints only;
OpenShell routing and the full reset/step/state session remain S5 work.

The installed `server/echo_environment.py` implements an **MCP-only** echo
environment. Its tool `echo_message` accepts a `message` argument. Although
`models.py` still defines `EchoAction`, the server rejects legacy actions.
For this candidate, a future hello step must use `CallToolAction` with
`tool_name="echo_message"` and `arguments={"message": "hello"}`; do not
assume `EchoAction(message="hello")` works. Client compatibility must be
verified before approving the candidate.

## Local driver blocker

CLI/gateway 0.0.116, workspace `default`, native macOS VM driver:

```bash
openshell sandbox create --workspace default --name oe-s3-echo \
  --from registry.hf.space/openenv-echo-env@sha256:5e6068b14b13cf829ccaefe0549e1dea0199f9509f056a3c90f748cf72271348 \
  --detach -- sh -c 'cd /app/env && uvicorn server.app:app --host 0.0.0.0 --port 8000'
```

The driver fetched and unpacked the image, then failed at VM supervisor startup:
`ProcessExited: VM process exited with status 0`. The image is amd64-only and
`command -v ip` inside it returned no executable. S2 separately established
that the VM lane requires `iproute2`. The provisioning output does not isolate
which incompatibility caused this failure; neither requirement can be assumed
satisfied.

The failed sandbox was deleted with `openshell sandbox delete`; the subsequent
workspace sandbox list was `[]`. No service was exposed for this failed VM.
Docker probe containers used `--rm`.

S3 remains blocked until a pinned native arm64 EchoEnv image with the VM's
required utilities is available and passes provisioning, or a supported amd64
compute backend is deliberately selected and validated. A derived image must
pin its source/base inputs and preserve the environment's server workload;
adding utilities alone does not fix an architecture mismatch. Revalidate with
the SDK/gateway pair selected by S1a. Do not change gateway configuration or
weaken policy to treat this candidate as compatible.

## Reproduce inspection

```bash
docker buildx imagetools inspect registry.hf.space/openenv-echo-env:latest
docker buildx imagetools inspect \
  registry.hf.space/openenv-echo-env@sha256:5e6068b14b13cf829ccaefe0549e1dea0199f9509f056a3c90f748cf72271348 \
  --format '{{json .Image}}'
```

The upstream [deployment tutorial][deployment] names this registry repository.
Its mutable documentation is not the source of truth for this pinned image's
port, action model, or architecture; inspect the digest before changing it.

[deployment]: https://github.com/huggingface/OpenEnv/blob/main/tutorial/02-deployment.md
