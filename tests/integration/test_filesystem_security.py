"""SEC5: real filesystem denials with readable canaries and a live client."""

from __future__ import annotations

from pathlib import Path
from shlex import quote
from typing import cast

import pytest
from openshell import SandboxClient

from openenv_openshell.policy import load_policy
from tests.integration._runtime import COMMAND, Runtime
from tests.openenv_client import client_factory

# These paths contain only synthetic fixtures baked into images/filesystem.
_CANARIES = ("/root/.ssh/id_rsa", "/host/etc/shadow")
_REPORT = "/tmp/sec5-initial.txt"  # noqa: S108 - Disposable guest file.
_PROBE = """
import errno
from pathlib import Path
import sys

denied = sys.argv[1] == "denied"
for name in ("/root/.ssh/id_rsa", "/host/etc/shadow"):
    try:
        value = Path(name).read_text()
    except OSError as error:
        assert denied and error.errno in (errno.EACCES, errno.EPERM), (
            "Expected policy denial, not missing fixture or another IO error"
        )
    else:
        assert not denied, "Forbidden canary was readable"
        assert value == "sec5-synthetic-canary\\n", "Wrong canary fixture"
for directory in ("/workspace", "/tmp"):
    path = Path(directory) / "sec5-write-control.txt"
    path.write_text("sec5-write-control")
    assert path.read_text() == "sec5-write-control"
    path.unlink()
print("sec5-probe-ok")
"""


@pytest.mark.integration
def test_filesystem_denials_preserve_session(openshell_runtime: Runtime) -> None:
    """Initial workload and exec deny existing files; reset/step/state still work."""
    policy_path = Path(__file__).parents[2] / "examples/policies/deny-all.yaml"
    strict = load_policy(policy_path)
    # Run both controls with the image's default identity. World-readable canaries
    # and identical identity exclude Unix ownership/mode as the denial cause.
    strict.pop("process")
    for denied in (False, True):
        policy = dict(strict)
        filesystem = dict(cast("dict[str, object]", strict["filesystem"]))
        if not denied:
            filesystem["read_only"] = [
                *cast("list[str]", filesystem["read_only"]),
                *_CANARIES,
            ]
        policy["filesystem"] = filesystem
        mode = "denied" if denied else "allowed"
        probe = f"/usr/local/bin/python3.12 -c {quote(_PROBE)} {mode}"
        command = ("sh", "-c", f"{probe} > {_REPORT} && {COMMAND[2]}")
        provider = openshell_runtime.provider(command=command, policy=policy)
        env = client_factory.from_docker_image(
            openshell_runtime.image, provider=provider
        ).sync()
        with env:
            assert not env.reset().done
            with SandboxClient.from_active_cluster(
                cluster=openshell_runtime.gateway, timeout=30
            ) as client:
                result = client.exec(
                    provider.config.sandbox_name or "",
                    ["/usr/local/bin/python3.12", "-c", _PROBE, mode],
                    workspace=openshell_runtime.workspace,
                    timeout_seconds=30,
                )
                assert result.exit_code == 0, "Filesystem exec probe failed"
                assert result.stdout.strip() == "sec5-probe-ok"
                initial = client.exec(
                    provider.config.sandbox_name or "",
                    ["cat", _REPORT],
                    workspace=openshell_runtime.workspace,
                    timeout_seconds=30,
                )
                assert initial.exit_code == 0
                assert initial.stdout.strip() == "sec5-probe-ok"
            # Keep the same WebSocket open across the security probes.
            result = env.step(
                {
                    "type": "call_tool",
                    "tool_name": "echo_message",
                    "arguments": {"message": "after-filesystem-probes"},
                }
            )
            assert result.observation["result"]["data"] == "after-filesystem-probes"
            assert not result.observation["result"]["is_error"]
            assert env.state()["step_count"] == 1
            assert not env.reset().done
            assert env.state()["step_count"] == 0
        assert provider.state.deleted
        with SandboxClient.from_active_cluster(
            cluster=openshell_runtime.gateway, timeout=30
        ) as client:
            assert not any(
                sandbox.name == provider.config.sandbox_name
                for sandbox in client.list(workspace=openshell_runtime.workspace).all()
            )
