"""Offline interruption, diagnostics, and cleanup contracts for the E2E owner."""

import signal
from unittest.mock import patch

import pytest

from tests.fakes import FakeOperation, FakeSandboxAdapter
from tests.integration._runtime import Runtime, RuntimeCleanupError, runtime_scope


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt, SystemExit])
def test_body_failure_cleans_all_and_restores_signal(
    failure: type[BaseException],
) -> None:
    """Every registered provider is deleted even when stack unwinding interrupts."""
    runtime = Runtime("private-image", "private-workspace")
    adapters = [FakeSandboxAdapter(), FakeSandboxAdapter()]
    previous = signal.getsignal(signal.SIGTERM)

    def run() -> None:
        with runtime_scope(runtime):
            for adapter in adapters:
                provider = runtime.provider(command=["server", "private-command"])
                with patch.object(provider, "_connect_adapter", return_value=adapter):
                    provider.start_container(
                        runtime.image, env_vars={"TOKEN": "secret"}
                    )
            raise failure

    with pytest.raises(failure):
        run()
    assert all(adapter.closed for adapter in adapters)
    assert all(provider.state.deleted for provider in runtime.providers)
    assert signal.getsignal(signal.SIGTERM) == previous
    assert "private" not in repr(runtime)
    assert "secret" not in repr(runtime)


def test_sigterm_unwinds_and_deletes() -> None:
    """Actual SIGTERM delivery exercises the installed interruption handler."""
    runtime = Runtime("image")
    adapter = FakeSandboxAdapter()
    previous = signal.getsignal(signal.SIGTERM)

    def run() -> None:
        with runtime_scope(runtime):
            provider = runtime.provider()
            with patch.object(provider, "_connect_adapter", return_value=adapter):
                provider.start_container(runtime.image)
            signal.raise_signal(signal.SIGTERM)

    with pytest.raises(KeyboardInterrupt):
        run()
    assert adapter.closed
    assert runtime.providers[0].state.deleted
    assert signal.getsignal(signal.SIGTERM) == previous


@pytest.mark.parametrize("primary", [False, True])
def test_cleanup_failure_attempts_other_providers_and_preserves_primary(
    *,
    primary: bool,
) -> None:
    """Cleanup failure remains visible without masking a test or exposing secrets."""
    runtime = Runtime("image")
    good = FakeSandboxAdapter()
    bad = FakeSandboxAdapter(failures={"delete": RuntimeError("private-sdk-token")})
    expected = ValueError if primary else RuntimeCleanupError

    def run() -> None:
        with runtime_scope(runtime):
            for adapter in (good, bad):
                provider = runtime.provider()
                with patch.object(provider, "_connect_adapter", return_value=adapter):
                    provider.start_container(runtime.image)
            if primary:
                msg = "body failed"
                raise ValueError(msg)

    with pytest.raises(expected) as caught:
        run()
    assert good.closed
    assert not bad.closed
    assert "private-sdk-token" not in str(caught.value)
    if primary:
        assert caught.value.__notes__ == [
            "E2E cleanup also failed; retry owned providers."
        ]


def test_setup_failure_before_start_is_safe() -> None:
    """Ownership registration before create permits teardown of unused providers."""
    runtime = Runtime("image")
    with runtime_scope(runtime):
        runtime.provider()
    assert runtime.providers[0].state.sandbox_name is None


@pytest.mark.parametrize("stage", ["create", "wait_ready"])
def test_interruption_during_startup_is_cleaned(stage: FakeOperation) -> None:
    """A BaseException at the RPC boundary cannot bypass fixture ownership."""
    runtime = Runtime("image")
    adapter = FakeSandboxAdapter(failures={stage: KeyboardInterrupt()})

    def run() -> None:
        with runtime_scope(runtime):
            provider = runtime.provider()
            with patch.object(provider, "_connect_adapter", return_value=adapter):
                provider.start_container(runtime.image)

    with pytest.raises(KeyboardInterrupt):
        run()
    assert adapter.closed
    assert runtime.providers[0].state.deleted


def test_transient_cleanup_failure_is_retried() -> None:
    """Retry a failed delete while retaining the original provider identity."""
    runtime = Runtime("image")
    adapter = FakeSandboxAdapter()
    provider = runtime.provider()
    with patch.object(provider, "_connect_adapter", return_value=adapter):
        provider.start_container(runtime.image)
    original = adapter.delete
    with patch.object(
        adapter,
        "delete",
        side_effect=[
            RuntimeError(),
            original(provider.config.sandbox_name or "", workspace=runtime.workspace),
        ],
    ):
        runtime.close()
    assert provider.state.deleted
    assert adapter.closed
    assert "provider cleanup attempt failed" in runtime.diagnostics
