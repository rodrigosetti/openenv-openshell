"""README quickstart: an unmodified OpenEnv client against EchoEnv in OpenShell.

Build the pinned EchoEnv image, then run from the repository root::

    docker build -t openenv-openshell-echo:quickstart \
      -f tests/integration/images/echo/Dockerfile tests/integration/images/echo
    export OPENENV_OPENSHELL_ECHO_IMAGE_ID="$(docker image inspect \
      --format '{{.Id}}' openenv-openshell-echo:quickstart)"
    uv run python examples/quickstart.py

Requires a prepared local OpenShell 0.1.2 gateway (``make openshell-smoke``).
"""

# OpenEnv's GenericEnvClient is untyped; keep the example free of casts.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

import os
from secrets import token_hex

from openenv.core.generic_client import GenericEnvClient

from openenv_openshell import OpenShellProvider

provider = OpenShellProvider(
    # The 0.1.2 gateway limits names to 19 characters.
    sandbox_name=f"oe-quick-{token_hex(4)}",
    # Exact server argv; OpenShell 0.1.2 does not run the image CMD for you.
    command=[
        "sh",
        "-c",
        "cd /app/env && uvicorn server.app:app --host 0.0.0.0 --port 8000",
    ],
    service_port=8000,
    policy="examples/policies/image-compatible.yaml",
    labels={"openenv.environment": "echo"},
)
image = os.environ["OPENENV_OPENSHELL_ECHO_IMAGE_ID"]
env = GenericEnvClient.from_docker_image(image, provider=provider).sync()
with env:
    env.reset()
    result = env.step(
        {
            "type": "call_tool",
            "tool_name": "echo_message",
            "arguments": {"message": "hello from OpenShell"},
        }
    )
    print("echo:", result.observation["result"]["data"])
    print("steps:", env.state()["step_count"])
    print("sandbox:", provider.metadata and provider.metadata.sandbox_name)
print("deleted:", provider.state.deleted)
