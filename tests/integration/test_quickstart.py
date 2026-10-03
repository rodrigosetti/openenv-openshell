"""I9: the README quickstart runs unmodified and deletes its sandbox."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from openshell import SandboxClient

_ROOT = Path(__file__).parents[2]


@pytest.mark.integration
def test_quickstart_script() -> None:
    """Run the documented command and verify its output and final absence."""
    if not os.environ.get("OPENENV_OPENSHELL_ECHO_IMAGE_ID"):
        pytest.skip("Set OPENENV_OPENSHELL_ECHO_IMAGE_ID to the EchoEnv image")
    result = subprocess.run(  # noqa: S603 - Fixed interpreter and repository script.
        [sys.executable, "examples/quickstart.py"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[:2] == ["echo: hello from OpenShell", "steps: 1"]
    match = re.fullmatch(r"sandbox: (openenv-[a-z0-9-]{1,4}-[0-9a-f]{6})", lines[2])
    assert match is not None
    assert lines[3:] == ["deleted: True"]
    workspace = os.environ.get("OPENSHELL_WORKSPACE", "default")
    with SandboxClient.from_active_cluster(timeout=30) as client:
        assert all(
            sandbox.name != match.group(1)
            for sandbox in client.list(workspace=workspace).all()
        )
