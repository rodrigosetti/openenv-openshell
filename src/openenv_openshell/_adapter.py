"""SDK-independent types for the private runtime boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Literal, Protocol

from openenv_openshell.errors import (
    OpenShellConnectionError,
    SandboxCreationError,
    SandboxDeletionError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from openenv_openshell.config import OpenShellResources

SDK_VERSION = "0.1.2"
_INSTALL_HINT = (
    "Install the official hash-pinned OpenShell 0.1.2 wheel; "
    "see https://github.com/rodrigosetti/openenv-openshell/blob/main/docs/releases.md "
    "or use uv sync --locked in a source checkout."
)


class CreateCollisionError(SandboxCreationError):
    """The gateway rejected create because the name was already occupied."""


class DeleteNotSentError(SandboxDeletionError):
    """The adapter proves no delete RPC was sent; ownership preflight may retry."""


@dataclass(frozen=True, slots=True)
class CreateRequest:
    """Resolved inputs; policy uses normalized protobuf field names."""

    workspace: str
    name: str
    image: str
    command: Sequence[str] = field(repr=False)
    environment: Mapping[str, str] = field(repr=False)
    service_name: str
    target_port: int
    labels: Mapping[str, str]
    providers: Sequence[str]
    resources: OpenShellResources | None
    policy: Mapping[str, object] | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class Sandbox:
    """Sandbox identity and create-time routes, independent of generated models."""

    name: str
    sandbox_id: str
    service_urls: Mapping[str, str] = field(
        default_factory=lambda: dict[str, str](), repr=False
    )


@dataclass(frozen=True, slots=True)
class Deletion:
    """Preserve deletion outcome and identity, including uncertain completion."""

    sandbox_id: str | None
    outcome: Literal["completed", "accepted", "already_absent", "unknown"] = "accepted"


class SandboxAdapter(Protocol):
    """The small synchronous lifecycle surface consumed by the provider."""

    def create(self, request: CreateRequest) -> Sandbox:
        """Create a workload and its service atomically."""
        ...

    def wait_ready(
        self, sandbox_name: str, *, workspace: str, timeout_s: float
    ) -> Sandbox:
        """Wait for sandbox readiness."""
        ...

    def service_url(self, sandbox: Sandbox, service_name: str) -> str | None:
        """Read a route from the create result, before readiness replaces it."""
        ...

    def delete(
        self, sandbox_name: str, *, workspace: str, expected_sandbox_id: str
    ) -> Deletion:
        """Check identity before requesting deletion, tolerating absence.

        The pinned API cannot make this check atomic with deletion.
        Raise DeleteNotSentError only when no delete RPC was dispatched. All
        other failures must be treated as potentially applied deletion.
        """
        ...

    def wait_deleted(
        self,
        sandbox_name: str,
        *,
        workspace: str,
        expected_sandbox_id: str,
        timeout_s: float,
    ) -> None:
        """Wait for deletion of the original identity."""
        ...

    def close(self) -> None:
        """Release client resources; does not delete sandboxes."""
        ...


def connect(*, gateway: str | None = None) -> SandboxAdapter:
    """Load the pinned SDK lazily and connect to a registered gateway."""
    try:
        installed = version("openshell")
    except PackageNotFoundError:
        raise OpenShellConnectionError(_INSTALL_HINT) from None
    if installed != SDK_VERSION:
        raise OpenShellConnectionError(_INSTALL_HINT)
    try:
        from openenv_openshell._sdk import (  # noqa: PLC0415 - Lazy SDK boundary.
            SDKAdapter,
        )
    except ImportError:
        raise OpenShellConnectionError(_INSTALL_HINT) from None
    return SDKAdapter.connect(gateway=gateway)
