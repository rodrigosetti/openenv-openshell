"""S6a compare omitted and explicit image commands on the pinned VM lane."""

import os

import pytest
from openshell import SandboxClient

from tests.integration._lifecycle_spike import run_spike
from tests.integration.test_protocol_spike import COMMAND, probe_protocol


@pytest.mark.integration
@pytest.mark.parametrize("explicit_command", [False, True], ids=["omitted", "explicit"])
def test_image_startup(explicit_command: bool) -> None:  # noqa: FBT001 - Test cases.
    """Record the 0.1.2 limitation and require protocol success with explicit CMD.

    Both cases use the same image, initial policy, atomic route and identity-aware
    cleanup. An upgrade that starts image CMD automatically must revisit the
    negative assertion rather than silently retaining this compatibility limit.
    """
    image = os.environ.get("OPENENV_OPENSHELL_ECHO_IMAGE_ID")
    if image is None:
        pytest.skip("Set OPENENV_OPENSHELL_ECHO_IMAGE_ID to the validated image ID")

    def probe(url: str) -> None:
        if explicit_command:
            probe_protocol(url)
        else:
            # Ready is not evidence of image CMD execution. No /ws assertion is
            # possible when the routed server never becomes healthy.
            with pytest.raises(AssertionError, match="Routed health timed out"):
                probe_protocol(url, health_timeout_s=10)

    with SandboxClient.from_active_cluster(timeout=30) as client:
        run_spike(
            client,
            image=image,
            workspace=os.environ.get("OPENSHELL_WORKSPACE", "default"),
            command=COMMAND if explicit_command else (),
            probe=probe,
        )
