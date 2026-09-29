"""Opt-in S3 image compatibility probe, separate from provider lifecycle tests."""

import os
import re
import shutil
import socket
import subprocess
import time
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from websockets.sync.client import connect


def _run(*args: str, timeout: float = 120) -> str:
    """Run a bounded public CLI operation without a host shell."""
    executable = shutil.which(args[0])
    assert executable is not None, f"Required executable missing: {args[0]}"
    return subprocess.run(  # noqa: S603 - Fixed CLI names; arguments never use a host shell.
        [executable, *args[1:]],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    ).stdout.strip()


@pytest.mark.integration
def test_echo_image_on_local_vm() -> None:
    """Prove native image startup, routed health and WebSocket, then deletion."""
    image = os.environ.get("OPENENV_OPENSHELL_ECHO_IMAGE_ID")
    if image is None:
        pytest.skip("Set OPENENV_OPENSHELL_ECHO_IMAGE_ID to a built arm64 sha256 ID")
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", image), (
        "Use an immutable local image ID"
    )
    workspace = os.environ.get("OPENSHELL_WORKSPACE", "default")
    assert _run("openshell", "--version") == "openshell 0.0.116"
    assert (
        _run("docker", "image", "inspect", image, "--format", "{{.Architecture}}")
        == "arm64"
    )
    command = _run(
        "docker", "image", "inspect", image, "--format", "{{index .Config.Cmd 2}}"
    )
    assert command == "cd /app/env && uvicorn server.app:app --host 0.0.0.0 --port 8000"
    name = f"oe-echo-{uuid4().hex[:8]}"
    try:
        _run(
            "openshell",
            "sandbox",
            "create",
            "--workspace",
            workspace,
            "--name",
            name,
            "--from",
            image,
            "--detach",
            "--",
            "sh",
            "-c",
            command,
        )
        _run(
            "openshell",
            "service",
            "expose",
            "--workspace",
            workspace,
            name,
            "8000",
            "echo",
        )
        details = _run(
            "openshell", "service", "get", "--workspace", workspace, name, "echo"
        )
        match = re.search(r"https?://[a-zA-Z0-9.:/_-]+", details)
        assert match is not None, "Gateway did not return a service URL"
        url = match.group(0).rstrip("/")
        deadline = time.monotonic() + 60
        while True:
            # curl resolves *.localhost on this setup without changing system DNS.
            result = subprocess.run(  # noqa: S603 - Gateway URL is a separate argv element.
                [
                    shutil.which("curl") or "curl",
                    "--fail",
                    "--silent",
                    "--show-error",
                    "--max-time",
                    "2",
                    f"{url}/health",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if result.returncode == 0:
                assert '"healthy"' in result.stdout
                break
            assert time.monotonic() < deadline, "Routed EchoEnv health timed out"
            time.sleep(0.5)
        websocket_url = url.replace("http", "ws", 1) + "/ws"
        parsed = urlsplit(url)
        assert parsed.hostname is not None
        assert parsed.hostname.endswith(".openshell.localhost"), (
            "Requires local VM route"
        )
        # Preserve the routed Host header while avoiding a system DNS requirement.
        with (
            socket.create_connection(
                ("127.0.0.1", parsed.port or 80), timeout=5
            ) as sock,
            connect(
                websocket_url,
                sock=sock,
                open_timeout=5,
                close_timeout=5,
                proxy=None,
            ),
        ):
            pass
    finally:
        _run("openshell", "sandbox", "delete", "--workspace", workspace, name)
        deadline = time.monotonic() + 30
        while name in _run(
            "openshell", "sandbox", "list", "--workspace", workspace, "--output", "json"
        ):
            assert time.monotonic() < deadline, f"Sandbox deletion timed out: {name}"
            time.sleep(0.5)
