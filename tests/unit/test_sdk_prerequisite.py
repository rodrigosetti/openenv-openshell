"""Public startup rejects SDK prerequisite failures in fresh processes."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("source", ["omitted", "mapping", "yaml"])
@pytest.mark.parametrize("failure", ["missing", "version", "import", "broken"])
def test_startup_prerequisite(source: str, failure: str, tmp_path: Path) -> None:
    """Every policy path fails safely before any SDK gateway operation."""
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text("version: 1\n", encoding="utf-8")
    program = """
import sys
from importlib.metadata import PackageNotFoundError
from traceback import format_exception
from unittest.mock import patch

from openenv_openshell import OpenShellProvider
from openenv_openshell.errors import OpenShellConnectionError

source, failure, path = sys.argv[1:]
secret = "private-import-diagnostic"
policy = {"omitted": None, "mapping": {"version": 1}, "yaml": path}[source]
provider = OpenShellProvider(command=["server"], policy=policy)
assert "openenv_openshell._sdk" not in sys.modules
metadata = {"return_value": "0.1.2"}
if failure == "missing":
    metadata = {"side_effect": PackageNotFoundError(secret)}
elif failure == "version":
    metadata = {"return_value": secret}
error = ImportError(secret) if failure == "import" else RuntimeError(secret)
with patch("openenv_openshell._adapter.version", **metadata), patch(
    "openenv_openshell._adapter.import_module", side_effect=error
) as imported:
    try:
        provider.start_container("image")
    except OpenShellConnectionError as caught:
        diagnostic = "".join(format_exception(caught))
        assert secret not in diagnostic
        assert "hash-pinned OpenShell 0.1.2 wheel" in diagnostic
        assert "docs/releases.md" in diagnostic
    else:
        raise AssertionError("startup accepted an unusable SDK")
    assert imported.call_count == (0 if failure in {"missing", "version"} else 1)
assert "openenv_openshell._sdk" not in sys.modules
assert not provider.state.created
assert provider.state.sandbox_name is None
provider.stop_container()
"""
    result = subprocess.run(  # noqa: S603 - Fixed program in isolated Python interpreter.
        [sys.executable, "-c", program, source, failure, str(policy_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
