"""I8: the canonical coding-agent demo runs unmodified and deletes its sandbox."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from openshell import SandboxClient

_SCRIPT = Path(__file__).parents[2] / "examples/coding_env.py"
# SPEC section 35 lines, in order, plus the approved-egress and session controls.
_STAGES = (
    "OpenShell sandbox created",
    "OpenEnv server healthy",
    "WebSocket connected",
    "task executed",
    "approved filesystem access succeeded",
    "forbidden filesystem access denied",
    "approved package index request succeeded",
    "forbidden network request denied",
    "OpenEnv session still healthy after denials",
    "sandbox deleted",
)


@pytest.mark.integration
def test_coding_demo_script() -> None:
    """Run the documented command and verify every stage and final absence."""
    image = os.environ.get("OPENENV_OPENSHELL_CODING_IMAGE_ID")
    if not image:
        pytest.skip("Set OPENENV_OPENSHELL_CODING_IMAGE_ID to the I8 demo image")
    result = subprocess.run(  # noqa: S603 - Fixed interpreter and repository script.
        [sys.executable, str(_SCRIPT), "--image", image],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert [
        line.startswith(f"\N{CHECK MARK} {stage}")
        for line, stage in zip(lines, _STAGES, strict=True)
    ] == [True] * len(_STAGES)
    match = re.search(r"sandbox created \((oe-demo-[0-9a-f]{8}),", lines[0])
    assert match is not None
    gateway = os.environ.get("OPENSHELL_GATEWAY") or None
    workspace = os.environ.get("OPENSHELL_WORKSPACE", "default")
    with SandboxClient.from_active_cluster(cluster=gateway, timeout=30) as client:
        assert all(
            sandbox.name != match.group(1)
            for sandbox in client.list(workspace=workspace).all()
        )
