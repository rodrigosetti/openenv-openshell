"""Deterministic HTTP readiness tests without sockets or an OpenShell runtime."""

from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
import pytest

from openenv_openshell import OpenShellProvider
from openenv_openshell.errors import OpenEnvReadinessTimeout


@dataclass
class Clock:
    """Advance only when the polling code or a fake request spends time."""

    now: float = 100.0
    sleeps: list[float] = field(default_factory=list[float])

    def monotonic(self) -> float:
        """Return a stable fake monotonic timestamp."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Record and consume the requested sleep budget."""
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """Make deadline tests fast and independent of wall-clock changes."""
    clock = Clock()
    monkeypatch.setattr("openenv_openshell.provider.monotonic", clock.monotonic)
    monkeypatch.setattr("openenv_openshell.provider.sleep", clock.sleep)
    return clock


def install_client(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.Client:
    """Use the real HTTP client against a deterministic in-memory transport."""
    client = httpx.Client(transport=httpx.MockTransport(handler))

    def factory(*, follow_redirects: bool) -> httpx.Client:
        assert follow_redirects is False
        return client

    monkeypatch.setattr("openenv_openshell.provider.httpx.Client", factory)
    return client


@pytest.mark.parametrize(
    ("base_url", "expected_url"),
    [
        ("https://env.example", "https://env.example/health"),
        ("https://env.example/", "https://env.example/health"),
        ("https://env.example/a%2Fb/", "https://env.example/a%2Fb/health"),
    ],
)
def test_health_success(
    monkeypatch: pytest.MonkeyPatch, clock: Clock, base_url: str, expected_url: str
) -> None:
    """HTTP 200 alone marks readiness and all HTTP resources are closed."""
    responses: list[httpx.Response] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == expected_url
        assert request.method == "GET"
        assert request.extensions["timeout"] == dict.fromkeys(
            ["connect", "read", "write", "pool"], 2.0
        )
        response = httpx.Response(200)
        responses.append(response)
        return response

    client = install_client(monkeypatch, handler)
    provider = OpenShellProvider()
    provider.wait_for_ready(base_url)

    assert provider.state.ready
    assert clock.sleeps == []
    assert client.is_closed
    assert responses[0].is_closed


def test_retries_statuses_and_transport_failures(
    monkeypatch: pytest.MonkeyPatch, clock: Clock
) -> None:
    """Non-200 statuses and network failures retry using the configured interval."""
    statuses = iter([503, 302, 204, 200])
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert str(request.url) == "https://env.example/service/health"
        if calls == 1:
            msg = "secret connection detail"
            raise httpx.ConnectError(msg, request=request)
        if calls == 2:  # noqa: PLR2004 - Second request exercises timeout recovery.
            msg = "secret timeout detail"
            raise httpx.ReadTimeout(msg, request=request)
        return httpx.Response(next(statuses), headers={"location": "/login"})

    client = install_client(monkeypatch, handler)
    provider = OpenShellProvider(health_poll_interval_s=0.25)
    provider.wait_for_ready("https://env.example/service/", timeout_s=5)

    assert provider.state.ready
    assert calls == 6  # noqa: PLR2004 - Two errors, three failed statuses, one success.
    assert clock.sleeps == [0.25] * 5
    assert client.is_closed


def test_deadline_bounds_requests_and_sleep(
    monkeypatch: pytest.MonkeyPatch, clock: Clock
) -> None:
    """Request time and sleeps consume one deadline, with no post-deadline probe."""
    budgets: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        budgets.append(request.extensions["timeout"])
        clock.now += 0.125
        return httpx.Response(503)

    client = install_client(monkeypatch, handler)
    provider = OpenShellProvider(
        health_poll_interval_s=0.25, health_request_timeout_s=0.5
    )
    provider.state.ready = True
    with pytest.raises(OpenEnvReadinessTimeout, match="health readiness timed out"):
        provider.wait_for_ready("https://env.example", timeout_s=1)

    assert budgets == [
        dict.fromkeys(["connect", "read", "write", "pool"], timeout)
        for timeout in [0.5, 0.5, 0.25]
    ]
    assert clock.sleeps == [0.25, 0.25, 0.125]
    assert clock.now == 100 + 1
    assert not provider.state.ready
    assert client.is_closed


def test_late_success_is_not_ready(
    monkeypatch: pytest.MonkeyPatch, clock: Clock
) -> None:
    """A response arriving at the deadline cannot declare readiness."""

    def handler(_request: httpx.Request) -> httpx.Response:
        clock.now += 1
        return httpx.Response(200)

    install_client(monkeypatch, handler)
    provider = OpenShellProvider()
    with pytest.raises(OpenEnvReadinessTimeout):
        provider.wait_for_ready("https://env.example", timeout_s=1)
    assert not provider.state.ready
    assert clock.sleeps == []


def test_timeout_does_not_expose_transport_secrets(
    monkeypatch: pytest.MonkeyPatch, clock: Clock
) -> None:
    """Neither the endpoint nor raw transport errors escape through exceptions."""

    def handler(request: httpx.Request) -> httpx.Response:
        clock.now += 1
        msg = "bearer top-secret"
        raise httpx.ConnectError(msg, request=request)

    client = install_client(monkeypatch, handler)
    provider = OpenShellProvider()
    with pytest.raises(OpenEnvReadinessTimeout) as caught:
        provider.wait_for_ready("https://env.example/private-secret", timeout_s=1)

    assert "secret" not in str(caught.value)
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    assert not provider.state.ready
    assert client.is_closed


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True])
def test_invalid_deadline(timeout: float) -> None:
    """Invalid deadlines fail before an HTTP request is attempted."""
    with pytest.raises(ValueError, match="timeout_s"):
        OpenShellProvider().wait_for_ready("https://env.example", timeout_s=timeout)


@pytest.mark.parametrize(
    "setting", ["health_poll_interval_s", "health_request_timeout_s"]
)
@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), True])
def test_invalid_polling_configuration(setting: str, value: float) -> None:
    """Both polling settings are validated at construction time."""
    if setting == "health_poll_interval_s":
        with pytest.raises(ValueError, match=setting):
            OpenShellProvider(health_poll_interval_s=value)
    else:
        with pytest.raises(ValueError, match=setting):
            OpenShellProvider(health_request_timeout_s=value)


@pytest.mark.parametrize(
    "url",
    [
        "/relative",
        "ftp://env.example",
        "https://",
        "https://user:secret@env.example",
        "https://env.example?token=secret",
        "https://env.example#secret",
        "https://env.example:secret",
    ],
)
def test_invalid_url_is_rejected_without_echoing_input(url: str) -> None:
    """Ambiguous endpoints fail safely before polling."""
    with pytest.raises(ValueError, match="base_url") as caught:
        OpenShellProvider().wait_for_ready(url)
    assert "secret" not in str(caught.value)
