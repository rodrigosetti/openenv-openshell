"""S4 disposable SDK experiment; run with python -m tests.integration._lifecycle_spike.

This file is the spike's private compatibility boundary. Generated models never
enter production APIs; all runtime calls use the public, pinned OpenShell SDK.
"""

from __future__ import annotations

import logging
import os
import re
import signal
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import uuid4

from openshell import DeletionOutcome, SandboxClient, ServiceExposure
from openshell._proto.openshell_pb2 import SandboxSpec, SandboxTemplate
from openshell._proto.sandbox_pb2 import SandboxPolicy

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from types import FrameType

logger = logging.getLogger(__name__)
SDK_VERSION = "0.1.2"
IMAGE_PIN = Path(__file__).parent / "images" / "echo" / "local-image-id.txt"


class SpikeError(RuntimeError):
    """An actionable failure without raw SDK diagnostics or credentials."""


def workload(image: str) -> SandboxSpec:
    """Embed the S3a image policy; leave CMD resolution to the runtime."""
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image) is None:
        msg = "Use the validated immutable local EchoEnv image ID."
        raise SpikeError(msg)
    # Fixed image-specific policy, equivalent to images/echo/policy.yaml.
    # This experiment does not implement the SEC1 general-purpose YAML loader.
    policy = SandboxPolicy(
        version=1,
        filesystem={
            "include_workdir": True,
            "read_only": [
                "/bin",
                "/usr",
                "/lib",
                "/proc",
                "/dev/urandom",
                "/etc",
                "/var/log",
                "/app",
            ],
            "read_write": ["/tmp", "/dev/null"],  # noqa: S108 - Guest policy paths.
        },
        landlock={"compatibility": "best_effort"},
    )
    return SandboxSpec(template=SandboxTemplate(image=image), policy=policy)


def run_spike(
    client: SandboxClient,
    *,
    image: str,
    workspace: str,
    command: Sequence[str] = (),
    probe: Callable[[str], None] | None = None,
) -> str:
    """Create an atomic route, wait ready, return its URL after verified deletion.

    The caller owns the client. A fresh, short random name bounds cleanup to
    this attempt, including a create RPC whose response was lost.
    """
    spec = workload(image)
    spec.command.extend(command)
    if client.health().version != SDK_VERSION:
        msg = "Use an OpenShell 0.1.2 gateway with the pinned SDK."
        raise SpikeError(msg)
    name = f"oe-s4-{uuid4().hex[:10]}"
    sandbox_id: str | None = None
    primary: BaseException | None = None
    try:
        sandbox = client.create(
            workspace=workspace,
            name=name,
            spec=spec,
            labels={"openenv-lifecycle-spike": name},
            service_exposures=[ServiceExposure(target_port=8000)],
        )
        sandbox_id = sandbox.id
        # Only create returns routes; wait_ready/get do not carry them.
        url = _route(sandbox.service_urls.get(""))
        ready = client.wait_ready(name, workspace=workspace, timeout_seconds=120)
        _check_identity(ready.id, sandbox_id)
        logger.info("Ready sandbox %s (ID %s); route %s", name, sandbox_id, url)
        if probe is not None:
            probe(url)
    except BaseException as failure:
        primary = failure
        raise
    else:
        return url
    finally:
        try:
            _delete(client, name=name, workspace=workspace, sandbox_id=sandbox_id)
            logger.info("Deleted sandbox %s; absence verified", name)
        except BaseException:  # noqa: BLE001 - Preserve primary error on interruption.
            logger.error("Cleanup failed for sandbox %s; inspect this name", name)  # noqa: TRY400 - No raw credential-bearing traceback.
            if primary is None:
                msg = "Sandbox cleanup failed; inspect the logged sandbox name."
                raise SpikeError(msg) from None
            primary.add_note("Sandbox cleanup also failed; inspect the logged name.")


def _route(url: str | None) -> str:
    if url is None:
        msg = "Create did not return the unnamed service URL."
        raise SpikeError(msg)
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        msg = "Create returned an unusable service URL."
        raise SpikeError(msg)
    return url


def _check_identity(actual: str, expected: str) -> None:
    if actual != expected:
        msg = "Sandbox identity changed while waiting for readiness."
        raise SpikeError(msg)


def _delete(
    client: SandboxClient,
    *,
    name: str,
    workspace: str,
    sandbox_id: str | None,
) -> None:
    deletion = client.delete(name, workspace=workspace, allow_missing=True)
    expected_id = sandbox_id or deletion.sandbox_id
    if expected_id is not None:
        client.wait_deleted(
            name,
            workspace=workspace,
            expected_sandbox_id=expected_id,
            timeout_seconds=60,
        )
    elif deletion.outcome not in {
        DeletionOutcome.COMPLETED,
        DeletionOutcome.ALREADY_ABSENT,
    }:
        msg = "Deletion was not confirmed and no sandbox identity is available."
        raise SpikeError(msg)


def _check_sdk() -> None:
    if version("openshell") != SDK_VERSION:
        msg = "Install the pinned SDK with uv sync --locked."
        raise SpikeError(msg)


def _interrupt(_signum: int, _frame: FrameType | None) -> None:
    raise KeyboardInterrupt


def main() -> int:
    """Run against the registered gateway without printing raw SDK errors."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    previous = signal.signal(signal.SIGTERM, _interrupt)
    try:
        _check_sdk()
        image = os.environ.get("OPENENV_OPENSHELL_ECHO_IMAGE_ID")
        if image is None:
            image = IMAGE_PIN.read_text().strip()
        # Validate inputs before acquiring a client or mutating the gateway.
        workload(image)
        with SandboxClient.from_active_cluster(timeout=30) as client:
            run_spike(
                client,
                image=image,
                workspace=os.environ.get("OPENSHELL_WORKSPACE", "default"),
            )
    except KeyboardInterrupt:
        logger.error("Spike interrupted; cleanup was attempted for any create request.")  # noqa: TRY400 - No raw traceback.
        return 130
    except Exception:  # noqa: BLE001 - CLI intentionally omits raw SDK details.
        logger.error("Spike failed; check versions, image and gateway diagnostics.")  # noqa: TRY400 - No raw credential-bearing traceback.
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
