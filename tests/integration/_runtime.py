"""Reusable E2E ownership and interruption handling, without runtime imports."""

from __future__ import annotations

import signal
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from openenv_openshell import OpenShellProvider

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping, Sequence
    from types import FrameType

COMMAND = (
    "sh",
    "-c",
    "cd /app/env && uvicorn server.app:app --host 0.0.0.0 --port 8000",
)
POLICY = Path(__file__).parent / "images/echo/policy.yaml"


class RuntimeCleanupError(RuntimeError):
    """The E2E owner could not confirm cleanup; raw errors stay private."""


@dataclass
class Runtime:
    """One test's providers, registered before any startup can occur."""

    image: str = field(repr=False)
    workspace: str = field(default="default", repr=False)
    gateway: str | None = field(default=None, repr=False)
    providers: list[OpenShellProvider] = field(
        default_factory=lambda: list[OpenShellProvider](), repr=False
    )
    diagnostics: list[str] = field(default_factory=lambda: list[str]())

    def provider(
        self,
        *,
        command: Sequence[str] = COMMAND,
        policy: str | Path | Mapping[str, object] = POLICY,
    ) -> OpenShellProvider:
        """Return an owned provider for protocol or security workloads."""
        provider = OpenShellProvider(
            workspace=self.workspace,
            gateway=self.gateway,
            sandbox_name=f"oe-e2e-{uuid4().hex[:10]}",
            command=command,
            policy=policy,
        )
        self.providers.append(provider)
        return provider

    def snapshot(self) -> None:
        """Capture fixed lifecycle flags, excluding workload and SDK contents."""
        for index, provider in enumerate(self.providers):
            state = provider.state
            self.diagnostics.append(
                f"provider[{index}] {provider.config.sandbox_name}: "
                f"created={state.created} ready={state.ready} "
                f"deleted={state.deleted} owned={state.sandbox_name is not None}"
            )

    def close(self) -> None:
        """Attempt all deletions, retry transient failures, and report failure."""
        failed = False
        for provider in reversed(self.providers):
            for _ in range(2):
                try:
                    provider.stop_container()
                    break
                except Exception:  # noqa: BLE001 - Never expose SDK errors/secrets.
                    self.diagnostics.append("provider cleanup attempt failed")
            else:
                failed = True
        self.snapshot()
        if failed:
            msg = "E2E cleanup failed; retry owned providers with stop_container()."
            raise RuntimeCleanupError(msg) from None


def interrupt(_signum: int, _frame: FrameType | None) -> None:
    """Convert catchable termination into normal Python stack unwinding."""
    raise KeyboardInterrupt


@contextmanager
def runtime_scope(runtime: Runtime) -> Generator[Runtime]:
    """Clean up on setup/body failure, Ctrl-C, and SIGTERM; restore handlers."""
    previous = signal.signal(signal.SIGTERM, interrupt)
    primary: BaseException | None = None
    try:
        yield runtime
    except BaseException as failure:
        primary = failure
        raise
    finally:
        runtime.snapshot()
        # Ignore further termination while bounded provider cleanup runs.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            runtime.close()
        except RuntimeCleanupError:
            if primary is None:
                raise
            primary.add_note("E2E cleanup also failed; retry owned providers.")
        finally:
            signal.signal(signal.SIGTERM, previous)
