"""Opt-in live S4 lifecycle check; no production provider behavior exercised."""

import os

import pytest

from tests.integration._lifecycle_spike import main


@pytest.mark.integration
def test_lifecycle_spike() -> None:
    """Create EchoEnv with an atomic unnamed route and confirm deletion."""
    if os.environ.get("OPENENV_OPENSHELL_ECHO_IMAGE_ID") is None:
        pytest.skip("Set OPENENV_OPENSHELL_ECHO_IMAGE_ID to the validated image ID")
    assert main() == 0
