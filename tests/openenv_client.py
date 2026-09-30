"""Typed test boundary for OpenEnv's untyped bootstrap and dispatch API.

These protocols describe the exercised public 0.6.0 surface; the implementation
remains the installed GenericEnvClient, with no subclass or transport override.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, Protocol, Self, cast

from openenv.core.generic_client import (  # pyright: ignore[reportMissingTypeStubs]
    GenericEnvClient,
)

if TYPE_CHECKING:
    from types import TracebackType

    from openenv_openshell import OpenShellProvider


class Result(Protocol):
    """OpenEnv StepResult fields used by client contract assertions."""

    observation: dict[str, Any]
    done: bool


class AsyncClient(Protocol):
    """Awaitable public methods when called from the client's event loop."""

    base_url: str | None

    def reset(self) -> Awaitable[Result]:
        """Reset an episode."""
        ...

    def step(self, action: dict[str, Any]) -> Awaitable[Result]:
        """Execute an action."""
        ...

    def state(self) -> Awaitable[dict[str, Any]]:
        """Read session state."""
        ...

    def close(self) -> Awaitable[None]:
        """Release the socket and owned provider."""
        ...

    async def __aenter__(self) -> Self:
        """Enter the client context."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the client on context exit."""
        ...


class SyncClient(Protocol):
    """Public synchronous wrapper surface."""

    def reset(self) -> Result:
        """Reset an episode."""
        ...

    def step(self, action: dict[str, Any]) -> Result:
        """Execute an action."""
        ...

    def state(self) -> dict[str, Any]:
        """Read session state."""
        ...

    def close(self) -> None:
        """Release the socket and owned provider."""
        ...

    def __enter__(self) -> Self:
        """Enter the client context."""
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the client on context exit."""
        ...


class Bootstrap(Awaitable[AsyncClient], Protocol):
    """Lazy upstream factory handle with async and sync resolution."""

    def sync(self) -> SyncClient:
        """Start the provider and connect the synchronous client."""
        ...


class ClientFactory(Protocol):
    """The public factory's provider and supported forwarded options."""

    def from_docker_image(
        self,
        image: str,
        *,
        provider: OpenShellProvider,
        port: int | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> Bootstrap:
        """Create an unresolved bootstrap handle."""
        ...


client_factory = cast("ClientFactory", GenericEnvClient)
