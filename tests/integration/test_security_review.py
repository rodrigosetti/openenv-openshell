"""SEC8: strict non-root workload/exec and bounded resource diagnostics."""

import json
import logging
from pathlib import Path
from shlex import quote
from typing import cast

import pytest
from openshell import SandboxClient

from openenv_openshell.policy import load_policy
from tests.integration._runtime import COMMAND, Runtime
from tests.openenv_client import client_factory

_REPORT = "/tmp/sec8-identity.json"  # noqa: S108 - Disposable guest report.
_PROBE = """
import json, os, resource
from pathlib import Path

assert os.getuid() == os.geteuid() == 1000, "Workload must use sandbox UID"
assert os.getgid() == os.getegid() == 1000, "Workload must use sandbox GID"
assert 0 not in os.getgroups(), "Workload must not retain root group"
path = Path('/workspace/sec8-write-control')
path.write_text('sec8')
assert path.read_text() == 'sec8'
path.unlink()
root = Path('/sys/fs/cgroup')
limits = []
# Inspect this process's cgroup and ancestors, never create load or fork children.
for entry in Path('/proc/self/cgroup').read_text().splitlines():
    if entry.startswith('0::'):
        relative = entry.split('::', 1)[1].lstrip('/')
        current = root / relative
        if '..' in current.parts:
            continue
        while current == root or root in current.parents:
            file = current / 'pids.max'
            if file.exists():
                limits.append(file.read_text().strip())
            if current == root:
                break
            current = current.parent
print(json.dumps({'uid': os.getuid(), 'gid': os.getgid(),
                  'pids_max': limits,
                  'rlimit_nproc': list(resource.getrlimit(resource.RLIMIT_NPROC))}))
"""


@pytest.mark.integration
def test_strict_non_root_identity(openshell_runtime: Runtime) -> None:
    """Verify initial and exec identities without claiming resource enforcement."""
    policy = load_policy(Path(__file__).parents[2] / "examples/policies/deny-all.yaml")
    filesystem = cast("dict[str, object]", policy["filesystem"])
    filesystem["read_only"] = [
        *cast("list[str]", filesystem["read_only"]),
        "/sys/fs/cgroup",
    ]
    command = (
        "sh",
        "-c",
        f"/usr/local/bin/python3.12 -c {quote(_PROBE)} > {_REPORT} && {COMMAND[2]}",
    )
    provider = openshell_runtime.provider(command=command, policy=policy)
    env = client_factory.from_docker_image(
        openshell_runtime.image, provider=provider
    ).sync()
    with env:
        assert not env.reset().done
        name = provider.state.sandbox_name
        assert name is not None
        with SandboxClient.from_active_cluster(
            cluster=openshell_runtime.gateway, timeout=30
        ) as client:
            for argv in (
                ["cat", _REPORT],
                ["/usr/local/bin/python3.12", "-c", _PROBE],
            ):
                result = client.exec(
                    name,
                    argv,
                    workspace=openshell_runtime.workspace,
                    timeout_seconds=30,
                    no_login_shell=True,
                )
                assert result.exit_code == 0, "Non-root security probe failed"
                report = json.loads(result.stdout)
                assert report["uid"] == report["gid"] == 1000  # noqa: PLR2004 - Fixture identity.
                logging.getLogger(__name__).info("SEC8 identity/resources: %s", report)
        result = env.step(
            {
                "type": "call_tool",
                "tool_name": "echo_message",
                "arguments": {"message": "after-non-root-probes"},
            }
        )
        assert result.observation["result"]["data"] == "after-non-root-probes"
        assert not result.observation["result"]["is_error"]
        assert env.state()["step_count"] == 1
    assert provider.state.deleted
    with SandboxClient.from_active_cluster(
        cluster=openshell_runtime.gateway, timeout=30
    ) as client:
        assert not any(
            sandbox.name == name
            for sandbox in client.list(workspace=openshell_runtime.workspace).all()
        )
