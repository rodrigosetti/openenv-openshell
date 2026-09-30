"""SEC7: managed credentials stay opaque to initial and exec processes."""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import subprocess
from pathlib import Path
from shlex import quote
from typing import TYPE_CHECKING
from unittest.mock import patch
from uuid import uuid4

import pytest
from openshell import SandboxClient, SandboxRef

from openenv_openshell import OpenShellProvider
from openenv_openshell._sdk import SDKAdapter
from openenv_openshell.policy import load_policy
from tests.integration.test_protocol_spike import COMMAND, probe_protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from openshell import ServiceExposure
    from openshell._proto.openshell_pb2 import SandboxSpec

logger = logging.getLogger(__name__)
_KEY = "SEC7_API_KEY"
_PLAIN = "sec7-ordinary-environment-control"
_SNAPSHOT = "/tmp/sec7-environment.json"  # noqa: S108 - Disposable guest path.


def _provider_cli(
    cli: str, workspace: str, arguments: list[str], *, secret: str
) -> None:
    result = subprocess.run(  # noqa: S603 - Resolved CLI; fixed test arguments.
        [cli, "provider", "--workspace", workspace, *arguments],
        env={**os.environ, _KEY: secret},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        # CLI output may contain credential material. Never attach it to errors.
        pytest.fail("SEC7 provider CLI operation failed; inspect gateway diagnostics")


def _check_environments(
    client: SandboxClient, name: str, workspace: str, secret: str
) -> None:
    """Capture environment prints without exposing their content in diagnostics."""
    probe = (
        "import json,os; "
        f"print(json.dumps([json.load(open({_SNAPSHOT!r})), "
        "dict(os.environ)]))"
    )
    result = client.exec(
        name,
        ["/usr/local/bin/python3.12", "-c", probe],
        workspace=workspace,
        timeout_seconds=30,
    )
    assert result.exit_code == 0, "Guest environment probe failed"
    leaked = secret in result.stdout or secret in result.stderr
    assert not leaked, "Managed credential was printable"
    environments = json.loads(result.stdout)
    for environment in environments:
        value = environment.get(_KEY, "")
        opaque = value.startswith("openshell:resolve:env:") and value.endswith(_KEY)
        assert opaque, "Expected a present managed credential placeholder"
        assert environment.get("SEC7_ORDINARY") == _PLAIN
    logger.info(
        "Initial workload and exec print placeholders; ordinary env is readable"
    )


def _delete_sandbox(
    client: SandboxClient,
    adapter: SDKAdapter,
    name: str,
    workspace: str,
    sandbox_id: str | None,
) -> None:
    """Confirm identity-aware deletion even when create returned no identity."""
    deletion = adapter.delete(name, workspace=workspace)
    expected_id = sandbox_id or deletion.sandbox_id
    if expected_id is not None:
        adapter.wait_deleted(
            name,
            workspace=workspace,
            expected_sandbox_id=expected_id,
            timeout_s=60,
        )
    else:
        assert deletion.outcome in {"completed", "already_absent"}
    assert not client.list(
        workspace=workspace, label_selector=f"openenv-sec7={name}"
    ).all()


def _workload_create(
    client: SandboxClient, provider_name: str, command: str
) -> Callable[..., SandboxRef]:
    """Supply the validated image command only at the test SDK boundary."""
    real_create = client.create

    def create_workload(
        *,
        workspace: str,
        name: str,
        spec: SandboxSpec,
        labels: Mapping[str, str],
        service_exposures: Sequence[ServiceExposure],
    ) -> SandboxRef:
        assert list(spec.providers) == [provider_name]
        assert _KEY not in spec.environment
        spec.command.extend(("sh", "-c", command))
        return real_create(
            workspace=workspace,
            name=name,
            spec=spec,
            labels=labels,
            service_exposures=service_exposures,
        )

    return create_workload


@pytest.mark.integration
def test_managed_credentials_are_not_printable(tmp_path: Path) -> None:
    """Use a synthetic provider, no external requests, and verify full cleanup."""
    image = os.environ.get("OPENENV_OPENSHELL_ECHO_IMAGE_ID")
    if image is None:
        pytest.skip("Set OPENENV_OPENSHELL_ECHO_IMAGE_ID to the validated image ID")
    cli = shutil.which("openshell")
    assert cli is not None, "Install the matching OpenShell 0.1.2 CLI"
    workspace = os.environ.get("OPENSHELL_WORKSPACE", "default")
    name = f"oe-sec7-{uuid4().hex[:8]}"
    provider_name = f"{name}-provider"
    secret = secrets.token_hex(32)
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        f"""id: {name}
display_name: SEC7 disposable fixture
description: Synthetic credential visibility test; no endpoint requests
category: other
credentials:
  - name: api_key
    env_vars: [{_KEY}]
    required: true
    auth_style: bearer
    header_name: authorization
endpoints:
  - host: sec7.example.invalid
    port: 443
    protocol: rest
    access: read-only
    enforcement: enforce
binaries: [/usr/local/bin/python3.12]
""",
        encoding="utf-8",
    )
    settings = OpenShellProvider(
        workspace=workspace,
        sandbox_name=name,
        providers=[provider_name],
        labels={"openenv-sec7": name},
    )
    policy = load_policy(Path(__file__).parent / "images/echo/policy.yaml")
    # Exercise P3 request preparation pending P4 startup wiring.
    request = settings._create_request(  # pyright: ignore[reportPrivateUsage] # noqa: SLF001
        image,
        policy=policy,
        env_vars={"SEC7_ORDINARY": _PLAIN},
    )
    # Snapshot the initial workload environment before starting the EchoEnv control.
    snapshot = (
        f"import json,os; open({_SNAPSHOT!r}, 'w').write(json.dumps(dict(os.environ)))"
    )
    command = f"/usr/local/bin/python3.12 -c {quote(snapshot)} && {COMMAND[2]}"
    imported = False
    provisioned = False
    try:
        _provider_cli(
            cli, workspace, ["profile", "import", "--file", str(profile)], secret=secret
        )
        imported = True
        _provider_cli(
            cli,
            workspace,
            [
                "create",
                "--name",
                provider_name,
                "--type",
                name,
                "--credential",
                _KEY,
            ],
            secret=secret,
        )
        provisioned = True
        with SandboxClient.from_active_cluster(timeout=30) as client:
            adapter = SDKAdapter(client)
            create_workload = _workload_create(client, provider_name, command)

            sandbox_id: str | None = None
            try:
                with patch.object(client, "create", side_effect=create_workload):
                    created = adapter.create(request)
                sandbox_id = created.sandbox_id
                adapter.wait_ready(name, workspace=workspace, timeout_s=120)
                url = adapter.service_url(created, "")
                assert url is not None
                probe_protocol(url)
                _check_environments(client, name, workspace, secret)
            finally:
                _delete_sandbox(client, adapter, name, workspace, sandbox_id)
    finally:
        try:
            if provisioned:
                _provider_cli(cli, workspace, ["delete", provider_name], secret=secret)
        finally:
            if imported:
                _provider_cli(
                    cli, workspace, ["profile", "delete", name], secret=secret
                )
    logger.info("SEC7 sandbox, provider and profile deleted")
