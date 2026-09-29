"""Exercise readiness over real loopback HTTP without an OpenShell gateway."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from openenv_openshell import OpenShellProvider
from openenv_openshell.errors import OpenEnvReadinessTimeout

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("healthy", [True, False])
def test_real_http_readiness(*, healthy: bool) -> None:
    """The HTTP transport detects health and times out on persistent failures."""
    paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            paths.append(self.path)
            self.send_response(200 if healthy else 503)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - Standard-library handler contract.
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            provider = OpenShellProvider(health_poll_interval_s=0.01)
            url = f"http://127.0.0.1:{server.server_port}"
            if healthy:
                provider.wait_for_ready(url, timeout_s=2)
                assert provider.state.ready
            else:
                with pytest.raises(OpenEnvReadinessTimeout):
                    provider.wait_for_ready(url, timeout_s=0.5)
                assert not provider.state.ready
            assert paths
            assert set(paths) == {"/health"}
        finally:
            server.shutdown()
            thread.join(timeout=2)
            assert not thread.is_alive()
