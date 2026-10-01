"""OpenEnv coding agent under OpenShell policy (SPEC section 35).

Runs the upstream OpenEnv ``coding_env`` server in an OpenShell sandbox, solves a
small coding task over the OpenEnv WebSocket, then uses the sandbox as an agent
tool would: approved ``/workspace`` and package-index access succeed, while
``~/.ssh``, host paths, and arbitrary internet hosts are denied by policy.

Build the pinned image, then run from the repository root::

    docker build -t openenv-openshell-coding:i8 examples/coding-agent
    OPENENV_OPENSHELL_CODING_IMAGE_ID="$(docker image inspect --format '{{.Id}}' \
      openenv-openshell-coding:i8)" uv run python examples/coding_env.py

The denied paths hold synthetic, world-readable canaries baked into the image;
no host files, SSH keys, or credentials are read. Requires a prepared local
OpenShell 0.1.2 gateway and internet access to ``pypi.org`` from the gateway.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from secrets import token_hex
from typing import TYPE_CHECKING, Any, Protocol, cast

from openenv.core.generic_client import (  # pyright: ignore[reportMissingTypeStubs]
    GenericEnvClient,
)
from openshell import SandboxClient

from openenv_openshell import OpenShellProvider, OpenShellProviderError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

POLICY = Path(__file__).parent / "coding-agent/policy.yaml"
COMMAND = (
    "/usr/local/bin/uvicorn",
    "coding_env.server.app:app",
    "--host",
    "0.0.0.0",  # noqa: S104 - Guest bind; ingress is the OpenShell service route.
    "--port",
    "8000",
)
PYTHON = "/usr/local/bin/python3.12"
SOLUTION = """\
def fizzbuzz(n):
    return "Fizz" * (n % 3 == 0) + "Buzz" * (n % 5 == 0) or str(n)

print(" ".join(fizzbuzz(n) for n in range(1, 16)))
"""
EXPECTED = "1 2 Fizz 4 Buzz Fizz 7 8 Fizz Buzz 11 Fizz 13 14 FizzBuzz"
WRITE_WORKSPACE = (
    "import pathlib, sys; "
    "pathlib.Path('/workspace/solution.py').write_text(sys.argv[1])"
)
# Only EACCES/EPERM count as denial; a missing canary or other error fails.
FILESYSTEM_PROBE = """
import errno, json, sys
try:
    open(sys.argv[1]).read()
    outcome = 'readable'
except OSError as error:
    denied = error.errno in (errno.EACCES, errno.EPERM)
    outcome = 'denied' if denied else 'other_error'
print(json.dumps(outcome))
"""
# Classify fixed outcomes only; never print exception text from the guest.
NETWORK_PROBE = """
import errno, json, sys, urllib.error, urllib.request
try:
    with urllib.request.urlopen('https://' + sys.argv[1] + '/', timeout=10) as r:
        outcome = r.status
except urllib.error.HTTPError as e:
    outcome = e.code
except urllib.error.URLError as e:
    if isinstance(e.reason, OSError) and e.reason.errno == errno.EACCES:
        outcome = 'denied'
    elif str(e.reason) == 'Tunnel connection failed: 403 Forbidden':
        outcome = 'denied'
    else:
        outcome = 'transport_error'
print(json.dumps(outcome))
"""


class DemoError(RuntimeError):
    """A demo expectation failed; the message names the failed check."""


class _Result(Protocol):
    observation: dict[str, Any]


class _Env(Protocol):
    def connect(self) -> object: ...
    def reset(self) -> _Result: ...
    def step(self, action: dict[str, Any]) -> _Result: ...
    def close(self) -> None: ...


class _Client(Protocol):
    def sync(self) -> _Env: ...


def _ok(message: str) -> None:
    print(f"\N{CHECK MARK} {message}", flush=True)


def _expect(condition: bool, failure: str) -> None:  # noqa: FBT001
    if not condition:
        raise DemoError(failure)


class Demo:
    """One sandbox, one OpenEnv session, and the agent's sandbox tool calls."""

    def __init__(self, image: str, workspace: str, gateway: str | None) -> None:
        """Configure the provider; no gateway contact happens here."""
        self.image = image
        self.workspace = workspace
        self.gateway = gateway
        self.provider = OpenShellProvider(
            workspace=workspace,
            gateway=gateway,
            sandbox_name=f"oe-demo-{token_hex(4)}",
            command=COMMAND,
            policy=POLICY,
        )
        self.name = self.provider.config.sandbox_name or ""

    def _exec(self, client: SandboxClient, *argv: str) -> str:
        result = client.exec(
            self.name,
            list(argv),
            workspace=self.workspace,
            timeout_seconds=30,
            no_login_shell=True,
        )
        _expect(result.exit_code == 0, "sandbox command failed")
        return result.stdout.strip()

    def _solve(self, env: _Env) -> None:
        """Run the candidate solution in the OpenEnv coding environment."""
        env.reset()
        observation = env.step({"code": SOLUTION}).observation
        _expect(observation.get("exit_code") == 0, "coding task failed")
        _expect(observation.get("stdout", "").strip() == EXPECTED, "wrong output")

    def run(self) -> None:
        """Execute the demo; the caller owns cleanup of the provider."""
        url = self.provider.start_container(self.image)
        metadata = self.provider.metadata
        digest = "" if metadata is None else (metadata.policy_digest or "")[:12]
        _ok(f"OpenShell sandbox created ({self.name}, policy {digest})")
        self.provider.wait_for_ready(url, timeout_s=120)
        _ok("OpenEnv server healthy")
        # OpenEnv's client is untyped; the protocols name the calls used here.
        client = cast("Callable[..., _Client]", GenericEnvClient)(base_url=url)
        env = client.sync()
        try:
            env.connect()
            _ok("WebSocket connected")
            self._solve(env)
            _ok("task executed (fizzbuzz via OpenEnv coding_env)")
            with SandboxClient.from_active_cluster(
                cluster=self.gateway, timeout=30
            ) as client:
                self._sandbox_tools(client)
            # The same WebSocket session keeps working after the denials.
            self._solve(env)
            _ok("OpenEnv session still healthy after denials")
        finally:
            env.close()

    def _sandbox_tools(self, client: SandboxClient) -> None:
        """Exercise approved and forbidden access as the agent's shell tool."""
        self._exec(client, PYTHON, "-c", WRITE_WORKSPACE, SOLUTION)
        output = self._exec(client, PYTHON, "/workspace/solution.py")
        _expect(output == EXPECTED, "workspace solution produced wrong output")
        _ok("approved filesystem access succeeded (/workspace)")
        for path in ("/root/.ssh/id_rsa", "/host/etc/shadow"):
            outcome = json.loads(
                self._exec(client, PYTHON, "-c", FILESYSTEM_PROBE, path)
            )
            _expect(outcome == "denied", f"{path} was not denied by policy")
        _ok("forbidden filesystem access denied (~/.ssh, /host)")
        outcome = json.loads(
            self._exec(client, PYTHON, "-c", NETWORK_PROBE, "pypi.org")
        )
        _expect(outcome == 200, "approved package index request failed")  # noqa: PLR2004
        _ok("approved package index request succeeded (pypi.org)")
        outcome = json.loads(
            self._exec(client, PYTHON, "-c", NETWORK_PROBE, "example.com")
        )
        _expect(outcome == "denied", "undeclared host was not denied by policy")
        _ok("forbidden network request denied (example.com)")

    def cleanup(self) -> None:
        """Delete the sandbox and confirm its absence independently."""
        self.provider.stop_container()
        with SandboxClient.from_active_cluster(cluster=self.gateway, timeout=30) as c:
            remaining = c.list(workspace=self.workspace).all()
        _expect(all(s.name != self.name for s in remaining), "sandbox still listed")
        _ok("sandbox deleted")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the demo and return a process exit status."""
    parser = argparse.ArgumentParser(
        description="OpenEnv coding agent under OpenShell policy"
    )
    parser.add_argument(
        "--image",
        default=os.environ.get("OPENENV_OPENSHELL_CODING_IMAGE_ID"),
        help="coding_env image ID (default: $OPENENV_OPENSHELL_CODING_IMAGE_ID)",
    )
    parser.add_argument(
        "--workspace", default=os.environ.get("OPENSHELL_WORKSPACE", "default")
    )
    parser.add_argument("--gateway", default=os.environ.get("OPENSHELL_GATEWAY"))
    args = parser.parse_args(argv)
    if not args.image:
        parser.error("set --image or OPENENV_OPENSHELL_CODING_IMAGE_ID")
    demo = Demo(cast("str", args.image), args.workspace, args.gateway)
    failure: str | None = None
    try:
        demo.run()
    except (DemoError, OpenShellProviderError) as error:
        failure = str(error)  # Checks and provider errors are secret-safe.
    except (Exception, KeyboardInterrupt) as error:  # noqa: BLE001
        # Raw SDK/transport messages may contain credentials or route data.
        failure = type(error).__name__
    try:
        demo.cleanup()
    except Exception as error:  # noqa: BLE001
        safe = isinstance(error, DemoError | OpenShellProviderError)
        detail = str(error) if safe else type(error).__name__
        print(f"\N{BALLOT X} cleanup: {detail}", file=sys.stderr)
        return 1
    if failure is not None:
        print(f"\N{BALLOT X} {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
