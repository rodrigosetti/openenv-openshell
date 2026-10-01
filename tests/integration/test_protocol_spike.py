"""S5 routed OpenEnv wire protocol check against the pinned EchoEnv image."""

import http.client
import json
import logging
import os
import socket
import ssl
import time
from contextlib import ExitStack
from functools import partial
from http import HTTPStatus
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import pytest
from openshell import SandboxClient
from websockets.sync.client import ClientConnection, connect

from tests.integration._lifecycle_spike import run_spike

logger = logging.getLogger(__name__)
COMMAND = (
    "sh",
    "-c",
    "cd /app/env && uvicorn server.app:app --host 0.0.0.0 --port 8000",
)
# TLS alerts for a route that demands a client certificate (TLS 1.3 and 1.2).
CLIENT_CERT_ALERTS = {
    "TLSV13_ALERT_CERTIFICATE_REQUIRED",
    "SSLV3_ALERT_HANDSHAKE_FAILURE",
}


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict), "Expected a protocol object"
    return cast("dict[str, object]", value)


def _exchange(
    ws: ClientConnection, message: dict[str, object], expected: str
) -> dict[str, object]:
    ws.send(json.dumps(message))
    response = _object(json.loads(ws.recv(timeout=10)))
    assert response.get("type") == expected, "Unexpected protocol response type"
    return _object(response["data"])


def _probe_session(ws: ClientConnection) -> None:
    """Check echo results and episode state across resets on one connection."""
    episodes: list[str] = []
    for _ in range(2):
        reset = _exchange(ws, {"type": "reset", "data": {}}, "observation")
        assert reset["done"] is False
        assert reset["reward"] == 0.0
        assert _object(reset["observation"]) == {}
        before = _exchange(ws, {"type": "state"}, "state")
        assert before["step_count"] == 0
        episode = before["episode_id"]
        assert isinstance(episode, str)
        assert episode
        episodes.append(episode)
        for count, message in enumerate(("hello", "hello again"), start=1):
            step = _exchange(
                ws,
                {
                    "type": "step",
                    "data": {
                        "type": "call_tool",
                        "tool_name": "echo_message",
                        "arguments": {"message": message},
                    },
                },
                "observation",
            )
            observation = _object(step["observation"])
            assert observation["tool_name"] == "echo_message"
            assert observation.get("error") is None
            result = _object(observation["result"])
            assert result["is_error"] is False
            assert result["data"] == message
            assert ws.ping().wait(timeout=5), "Routed WebSocket pong timed out"
            state = _exchange(ws, {"type": "state"}, "state")
            assert state["episode_id"] == episode
            assert state["step_count"] == count
    assert episodes[0] != episodes[1], "Reset must create a fresh episode"
    ws.send(json.dumps({"type": "close"}))


def probe_protocol(
    url: str, *, health_timeout_s: float = 60, client_cert: Path | None = None
) -> None:
    """Assert health and two episodes over one gateway-routed WebSocket.

    Remote routes must use HTTPS with default certificate verification; supply
    a private gateway CA through SSL_CERT_FILE rather than disabling checks.
    ``client_cert`` names a directory holding ``tls.crt`` and ``tls.key`` to
    present to routes that require a TLS client certificate. An unmodified
    OpenEnv client cannot do this, so such runs validate transport only.
    """
    parsed = urlsplit(url)
    assert parsed.hostname is not None
    local = parsed.hostname.endswith(".openshell.localhost")
    assert not local or parsed.scheme == "http", "Use the local HTTP service route"
    assert local or parsed.scheme == "https", "Remote service routes require HTTPS"
    host = "127.0.0.1" if local else parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    context = None
    if not local:
        context = ssl.create_default_context()
        if client_cert is not None:
            context.load_cert_chain(client_cert / "tls.crt", client_cert / "tls.key")
    path = parsed.path.rstrip("/")
    deadline = time.monotonic() + health_timeout_s
    while True:
        connection = (
            http.client.HTTPConnection(host, port, timeout=2)
            if context is None
            else http.client.HTTPSConnection(host, port, timeout=2, context=context)
        )
        try:
            connection.request("GET", path + "/health", headers={"Host": parsed.netloc})
            response = connection.getresponse()
            if response.status == HTTPStatus.OK:
                assert _object(json.loads(response.read()))["status"] == "healthy"
                break
        except ssl.SSLCertVerificationError:
            pytest.fail("Service route certificate is not trusted", pytrace=False)
        except ssl.SSLError as error:
            if error.reason in CLIENT_CERT_ALERTS:
                pytest.fail(
                    "Service route requires a TLS client certificate", pytrace=False
                )
        except (OSError, http.client.HTTPException):
            pass
        finally:
            connection.close()
        assert time.monotonic() < deadline, "Routed health timed out"
        time.sleep(0.5)
    logger.info("Routed /health returned HTTP 200 and healthy status")
    ws_url = parsed._replace(
        scheme="wss" if parsed.scheme == "https" else "ws", path=path + "/ws"
    ).geturl()
    with ExitStack() as stack:
        sock = (
            stack.enter_context(socket.create_connection((host, port), timeout=5))
            if local
            else None
        )
        ws = stack.enter_context(
            connect(
                ws_url,
                sock=sock,
                ssl=context,
                open_timeout=5,
                close_timeout=5,
                proxy=None,
            )
        )
        _probe_session(ws)
    logger.info("Routed /ws passed two reset/step/state episodes and four echo steps")


@pytest.mark.integration
def test_protocol_spike() -> None:
    """Verify the live protocol before identity-aware sandbox deletion."""
    image = os.environ.get("OPENENV_OPENSHELL_ECHO_IMAGE_ID")
    if image is None:
        pytest.skip("Set OPENENV_OPENSHELL_ECHO_IMAGE_ID to the validated image ID")
    cert_dir = os.environ.get("OPENENV_OPENSHELL_PROBE_CLIENT_CERT_DIR")
    client_cert = Path(cert_dir) if cert_dir else None
    with SandboxClient.from_active_cluster(timeout=30) as client:
        run_spike(
            client,
            image=image,
            workspace=os.environ.get("OPENSHELL_WORKSPACE", "default"),
            command=COMMAND,
            probe=partial(probe_protocol, client_cert=client_cert),
        )
