"""Offline transport contracts for the S5/S5a routed protocol probe."""

import http.client
import ssl
from pathlib import Path
from unittest.mock import ANY, MagicMock

import pytest

from tests.integration.test_protocol_spike import probe_protocol

REMOTE = "https://sandbox--echo.gateway.test"


@pytest.fixture
def https(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace HTTPS connections; tests program the health response."""
    factory = MagicMock()
    monkeypatch.setattr(http.client, "HTTPSConnection", factory)
    return factory


def test_remote_plaintext_rejected(https: MagicMock) -> None:
    """A non-loopback route must not be probed without TLS."""
    with pytest.raises(AssertionError, match="HTTPS"):
        probe_protocol("http://sandbox--echo.gateway.test")
    https.assert_not_called()


def test_untrusted_certificate_fails_fast(https: MagicMock) -> None:
    """Certificate errors surface immediately instead of as a health timeout."""
    https.return_value.request.side_effect = ssl.SSLCertVerificationError("private")
    with pytest.raises(pytest.fail.Exception, match="not trusted") as caught:
        probe_protocol(REMOTE, health_timeout_s=3600)
    assert "private" not in str(caught.value)
    https.assert_called_once_with(
        "sandbox--echo.gateway.test", 443, timeout=2, context=ANY
    )
    https.return_value.close.assert_called_once()


def test_client_certificate_required_fails_fast(https: MagicMock) -> None:
    """A route demanding a client certificate fails explicitly."""
    error = ssl.SSLError(1, "private")
    error.reason = "TLSV13_ALERT_CERTIFICATE_REQUIRED"
    https.return_value.getresponse.side_effect = error
    with pytest.raises(pytest.fail.Exception, match="client certificate"):
        probe_protocol(REMOTE, health_timeout_s=3600)
    https.assert_called_once()


def test_client_certificate_is_presented(
    https: MagicMock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An opt-in certificate directory loads into the verifying TLS context."""
    context = MagicMock(spec=ssl.SSLContext)
    monkeypatch.setattr(ssl, "create_default_context", lambda: context)
    https.return_value.request.side_effect = ssl.SSLCertVerificationError("stop")
    with pytest.raises(pytest.fail.Exception):
        probe_protocol(REMOTE, client_cert=tmp_path)
    context.load_cert_chain.assert_called_once_with(
        tmp_path / "tls.crt", tmp_path / "tls.key"
    )
    assert https.call_args.kwargs["context"] is context
