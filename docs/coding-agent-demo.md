# Coding-agent demo (I8)

`examples/coding_env.py` is the reference demo from
[SPEC section 35](../SPEC.md#35-reference-demo): an OpenEnv coding environment
running under an OpenShell policy, with approved and forbidden access shown
side by side and sandbox deletion at the end.

## What runs

- **Environment:** upstream OpenEnv `envs/coding_env` (`PythonCodeActEnv`, backed
  by smolagents' `LocalPythonExecutor`) from the same pinned source revision as the
  EchoEnv fixture, built natively by [`examples/coding-agent/Dockerfile`](../examples/coding-agent/Dockerfile).
- **Client:** the unmodified OpenEnv 0.6.0 `GenericEnvClient`, connected to the
  OpenShell-managed service route over WebSocket. The task (FizzBuzz) is a
  `{"code": ...}` action whose stdout and exit code are checked.
- **Agent tools:** OpenShell SDK `exec` calls in the same sandbox, standing in for
  an agent's shell tool. They write and run the solution in `/workspace`, then
  probe forbidden files and hosts.
- **Policy:** [`examples/coding-agent/policy.yaml`](../examples/coding-agent/policy.yaml)
  is `deny-all.yaml` (hard-required Landlock, `sandbox` identity, writes only to
  `/workspace`, `/tmp`, `/dev/null`) plus one enforced read-only REST rule for
  `/usr/local/bin/python3.12` to `pypi.org:443`, representing a package index.

The image bakes **synthetic**, world-readable canaries at `/root/.ssh/id_rsa` and
`/host/etc/shadow` and a `sandbox` user (UID/GID 1000). Unix permissions allow
reading the canaries, so a denial can only come from the policy. No host
directory is mounted and no real key or credential is read.

## Run it

Prerequisites: the [local OpenShell setup](local-openshell-testing.md) with
`make openshell-smoke` passing (SDK/gateway 0.1.2), Docker, and gateway internet
access to `pypi.org` and `example.com`.

```bash
docker build -t openenv-openshell-coding:i8 examples/coding-agent
export OPENENV_OPENSHELL_CODING_IMAGE_ID="$(docker image inspect --format '{{.Id}}' openenv-openshell-coding:i8)"
make demo   # or: uv run python examples/coding_env.py
```

`OPENSHELL_GATEWAY` and `OPENSHELL_WORKSPACE` (or `--gateway`/`--workspace`)
select a non-default gateway or workspace. Expected output:

```text
✓ OpenShell sandbox created (oe-demo-e531c976, policy 5104817a61fe)
✓ OpenEnv server healthy
✓ WebSocket connected
✓ task executed (fizzbuzz via OpenEnv coding_env)
✓ approved filesystem access succeeded (/workspace)
✓ forbidden filesystem access denied (~/.ssh, /host)
✓ approved package index request succeeded (pypi.org)
✓ forbidden network request denied (example.com)
✓ OpenEnv session still healthy after denials
✓ sandbox deleted
```

The sandbox name is random per run; the policy prefix is the submitted-policy
digest from `provider.metadata`. Any failed check prints `✗` with the check name
(or only an exception type, never raw SDK text), still deletes the sandbox, and
exits non-zero. Ctrl-C also runs cleanup.

## What each check establishes

| Line | Check |
| --- | --- |
| sandbox created | `start_container()` submitted command, service, and explicit policy in one create request |
| server healthy | `wait_for_ready()` saw HTTP 200 from `/health` over the service route |
| WebSocket connected / task executed | The OpenEnv client ran the FizzBuzz action; stdout matched and exit code was 0 |
| approved filesystem | The solution was written to and run from `/workspace` as the `sandbox` user |
| forbidden filesystem | Reads of both canaries failed with `EACCES`/`EPERM`; missing files or other errors fail the demo |
| approved package index | `https://pypi.org/` returned HTTP 200 from the guest, so egress itself works |
| forbidden network | `https://example.com/` was refused by the proxy (403 CONNECT) or with `EACCES` |
| session still healthy | A second reset/step on the same WebSocket succeeded after all denials |
| sandbox deleted | `stop_container()` confirmed deletion by identity, and a separate SDK listing no longer shows the name |

`tests/integration/test_coding_demo.py` runs the script unchanged, asserts every
line in order, and checks absence again. It skips without
`OPENENV_OPENSHELL_CODING_IMAGE_ID`:

```bash
uv run pytest -m integration --no-cov tests/integration/test_coding_demo.py -v
```

## Evidence

Verified on 2026-09-30 with local SDK/gateway 0.1.2 on the native arm64 VM lane,
image `sha256:84e0e12d569a4bbf9f0a6ae1884c9ddf1409083b9298b1b75c19e11dace87068`
built from this Dockerfile. The demo printed all ten lines and exited 0; the
integration test passed. A one-off positive control with the same image, adding
the two canary paths to `read_only`, read both canaries as
`uid=1000(sandbox)`, confirming the demo's denial comes from Landlock policy
rather than file permissions or a missing fixture. That control sandbox was
also deleted.

## Limits

- The image is built locally from pinned upstream source; it is not a published
  Hugging Face Space image or registry digest. Other architectures and compute
  drivers are unverified.
- The SPEC diagram's model inference endpoint is not exercised: the demo holds
  no model credentials and makes no inference calls. Add a reviewed endpoint rule
  and an OpenShell-managed credential provider for that case (see
  [security guide](security.md#configure-credentials-outside-the-workload)).
- The pypi.org rule illustrates a package-index read; it does not make `pip
  install` work (files are served from `files.pythonhosted.org`, and pip is not the
  allowed binary).
- `coding_env`'s executor authorizes only the `json` import by default, so
  agent code cannot reach files or sockets through it. The filesystem and
  network probes therefore run through SDK `exec`; the denials shown are
  OpenShell's, not the executor's.
- The residual risks in the [security guide](security.md) apply, including the
  SEC8a cleanup-ownership finding and the process-capacity exclusion.
