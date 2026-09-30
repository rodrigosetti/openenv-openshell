"""SEC6: egress policy controls destinations without breaking OpenEnv routing."""

import json
import logging

import pytest
from openshell import SandboxClient

from openenv_openshell.policy import load_policy
from tests.integration._runtime import POLICY, Runtime
from tests.openenv_client import SyncClient, client_factory

logger = logging.getLogger(__name__)
PYTHON = "/usr/local/bin/python3.12"
HOSTS = ("huggingface.co", "example.com")
# Run in the guest, not on the trainer. Never treat arbitrary transport failures
# as policy denial; return only a fixed classification, not exception contents.
PROBE = """
import errno, json, sys, urllib.error, urllib.request
try:
    with urllib.request.urlopen('https://' + sys.argv[1] + '/', timeout=10) as r:
        result = {'outcome': 'response', 'status': r.status}
except urllib.error.HTTPError as e:
    result = {'outcome': 'http_error', 'status': e.code}
except urllib.error.URLError as e:
    if isinstance(e.reason, OSError) and e.reason.errno == errno.EACCES:
        result = {'outcome': 'permission_denied', 'errno': errno.EACCES}
    elif str(e.reason) == 'Tunnel connection failed: 403 Forbidden':
        result = {'outcome': 'connect_denied', 'status': 403}
    else:
        result = {'outcome': 'transport_error'}
print(json.dumps(result))
"""


def _session_control(env: SyncClient, message: str) -> None:
    """Exercise the same persistent client connection around guest denials."""
    assert not env.reset().done
    assert env.state()["step_count"] == 0
    result = env.step(
        {
            "type": "call_tool",
            "tool_name": "echo_message",
            "arguments": {"message": message},
        }
    )
    assert result.observation["result"]["data"] == message
    assert not result.observation["result"]["is_error"]
    assert env.state()["step_count"] == 1


@pytest.mark.integration
@pytest.mark.parametrize("allowed_host", HOSTS)
def test_network_policy(openshell_runtime: Runtime, allowed_host: str) -> None:
    """Compare deny-all with a single allowed HTTPS destination and binary."""
    runtime = openshell_runtime
    for allow in (False, True):
        policy = load_policy(POLICY)
        if allow:
            policy["network_policies"] = {
                "sec6-read": {
                    "binaries": [{"path": PYTHON}],
                    "endpoints": [
                        {
                            "host": allowed_host,
                            "port": 443,
                            "protocol": "rest",
                            "enforcement": "enforce",
                            "access": "read_only",
                        }
                    ],
                }
            }
        provider = runtime.provider(policy=policy)
        env = client_factory.from_docker_image(runtime.image, provider=provider).sync()
        with (
            SandboxClient.from_active_cluster(
                cluster=runtime.gateway, timeout=30
            ) as client,
            env,
        ):
            name = provider.state.sandbox_name
            assert name is not None
            _session_control(env, "before egress")
            for host in HOSTS:
                result = client.exec(
                    name,
                    [PYTHON, "-c", PROBE, host],
                    workspace=runtime.workspace,
                    timeout_seconds=20,
                    no_login_shell=True,
                )
                assert result.exit_code == 0, "Guest HTTPS probe failed"
                outcome = json.loads(result.stdout)
                if allow and host == allowed_host:
                    assert outcome == {"outcome": "response", "status": 200}
                else:
                    assert outcome in (
                        {"outcome": "permission_denied", "errno": 13},
                        {"outcome": "connect_denied", "status": 403},
                    )
                _session_control(env, "after egress")
                logger.info("SEC6 %s: %s", host, outcome)
        assert provider.state.deleted
        with SandboxClient.from_active_cluster(
            cluster=runtime.gateway, timeout=30
        ) as client:
            assert not any(
                sandbox.name == name
                for sandbox in client.list(workspace=runtime.workspace).all()
            )
